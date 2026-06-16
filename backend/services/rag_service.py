from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import Meeting, MeetingStatus, TranscriptChunk
from services.embedding_service import embed_chunks

from openai import OpenAI


QUESTION_STARTERS = {
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "can",
    "could",
    "should",
    "would",
    "is",
    "are",
    "do",
    "does",
    "did",
}
PAST_MEETING_PATTERN = re.compile(
    r"\b(previous|last|prior|earlier|past|before|speaker\s*\d+|speaker\s+(one|two|three|four|five))\b",
    re.IGNORECASE,
)


async def search(session: AsyncSession, query: str, limit: int = 5) -> dict:
    query_vector = embed_chunks([query])[0]
    distance = TranscriptChunk.embedding.cosine_distance(query_vector)

    stmt = (
        select(
            TranscriptChunk.text,
            Meeting.title,
            (1 - distance).label("similarity"),
        )
        .join(Meeting, Meeting.id == TranscriptChunk.meeting_id)
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    sources = [
        {
            "meeting_title": title,
            "chunk_text": text,
            "similarity": float(similarity),
        }
        for text, title, similarity in rows
    ]

    if not sources:
        return {"answer": "No matching meeting context was found.", "sources": []}

    context = "\n\n".join(
        f"Source {index + 1} - {source['meeting_title']}:\n{source['chunk_text']}"
        for index, source in enumerate(sources)
    )
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer questions using only the meeting context. "
                    "If the context is insufficient, say what is missing."
                ),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
    )
    return {
        "answer": response.choices[0].message.content or "",
        "sources": sources,
    }


async def retrieve_past_meeting_context(
    session: AsyncSession,
    current_meeting_id: UUID,
    questions: list[Any],
    transcript: str = "",
    *,
    questions_limit: int = 3,
    sources_per_question: int = 3,
    min_similarity: float = 0.08,
) -> dict[str, Any]:
    query_texts = _query_texts(questions, transcript, questions_limit)
    if not query_texts:
        return _empty_context()

    query_vectors = await asyncio.to_thread(embed_chunks, query_texts)
    queries = []
    seen_chunks: set[str] = set()

    for question, query_vector in zip(query_texts, query_vectors):
        distance = TranscriptChunk.embedding.cosine_distance(query_vector)
        stmt = (
            select(
                TranscriptChunk.id,
                TranscriptChunk.text,
                TranscriptChunk.start_time,
                TranscriptChunk.end_time,
                Meeting.id.label("meeting_id"),
                Meeting.title,
                Meeting.created_at,
                (1 - distance).label("similarity"),
            )
            .join(Meeting, Meeting.id == TranscriptChunk.meeting_id)
            .where(
                TranscriptChunk.meeting_id != current_meeting_id,
                Meeting.status == MeetingStatus.complete,
            )
            .order_by(distance)
            .limit(sources_per_question * 3)
        )
        rows = (await session.execute(stmt)).all()
        sources = []
        for row in rows:
            similarity = float(row.similarity or 0)
            if similarity < min_similarity:
                continue
            chunk_key = str(row.id)
            if chunk_key in seen_chunks:
                continue
            seen_chunks.add(chunk_key)
            sources.append(
                {
                    "meeting_id": str(row.meeting_id),
                    "meeting_title": row.title,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "chunk_text": _trim_chunk(row.text),
                    "similarity": round(similarity, 4),
                    "start_time": round(float(row.start_time or 0), 2),
                    "end_time": round(float(row.end_time or 0), 2),
                }
            )
            if len(sources) >= sources_per_question:
                break
        if not sources and _needs_recent_meeting_context(question):
            sources = await _recent_previous_sources(
                session,
                current_meeting_id,
                limit=sources_per_question,
                seen_chunks=seen_chunks,
            )
        queries.append({"question": question, "sources": sources})

    return {
        "enabled": True,
        "source": "past_meetings_pgvector",
        "queries": queries,
        "source_count": sum(len(item["sources"]) for item in queries),
    }


def _empty_context() -> dict[str, Any]:
    return {
        "enabled": True,
        "source": "past_meetings_pgvector",
        "queries": [],
        "source_count": 0,
    }


def _query_texts(questions: list[Any], transcript: str, limit: int) -> list[str]:
    texts = []
    seen = set()
    for item in [*questions, *_transcript_query_candidates(transcript)]:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("question") or "").strip()
        else:
            text = str(item or "").strip()
        if not text:
            continue
        normalized = " ".join(text.lower().split())
        if normalized in seen:
            continue
        seen.add(normalized)
        texts.append(text)
        if len(texts) >= limit:
            break
    return texts


def _transcript_query_candidates(transcript: str, limit: int = 6) -> list[str]:
    recent = str(transcript or "")[-4000:]
    parts = re.split(r"(?<=[?.!])\s+|\n+", recent)
    candidates = []
    for part in parts:
        text = " ".join(part.split()).strip()
        if len(text) < 8:
            continue
        if _looks_like_query(text):
            candidates.append(text)
    return candidates[-limit:]


def _looks_like_query(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    first_word = stripped.split(" ", 1)[0].lower().strip(".,:;!?")
    if first_word in QUESTION_STARTERS:
        return True
    return _needs_recent_meeting_context(stripped)


def _needs_recent_meeting_context(text: str) -> bool:
    return bool(PAST_MEETING_PATTERN.search(text or ""))


async def _recent_previous_sources(
    session: AsyncSession,
    current_meeting_id: UUID,
    *,
    limit: int,
    seen_chunks: set[str],
) -> list[dict[str, Any]]:
    stmt = (
        select(
            TranscriptChunk.id,
            TranscriptChunk.text,
            TranscriptChunk.start_time,
            TranscriptChunk.end_time,
            Meeting.id.label("meeting_id"),
            Meeting.title,
            Meeting.created_at,
        )
        .join(Meeting, Meeting.id == TranscriptChunk.meeting_id)
        .where(
            TranscriptChunk.meeting_id != current_meeting_id,
            Meeting.status == MeetingStatus.complete,
        )
        .order_by(Meeting.created_at.desc(), TranscriptChunk.start_time.asc())
        .limit(limit * 3)
    )
    rows = (await session.execute(stmt)).all()
    sources = []
    for row in rows:
        chunk_key = str(row.id)
        if chunk_key in seen_chunks:
            continue
        seen_chunks.add(chunk_key)
        sources.append(
            {
                "meeting_id": str(row.meeting_id),
                "meeting_title": row.title,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "chunk_text": _trim_chunk(row.text),
                "similarity": 0.0,
                "start_time": round(float(row.start_time or 0), 2),
                "end_time": round(float(row.end_time or 0), 2),
                "fallback": "recent_previous_meeting",
            }
        )
        if len(sources) >= limit:
            break
    return sources


def _trim_chunk(text: str, max_chars: int = 900) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return f"{clean[: max_chars - 1].rstrip()}..."
