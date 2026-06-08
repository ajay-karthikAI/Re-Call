from collections.abc import Sequence
from uuid import UUID

from openai import OpenAI
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import TranscriptChunk


def chunk_text(transcript: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = transcript.split()
    if not words:
        return []

    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_size]).strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(words):
            break
    return chunks


def embed_chunks(chunks: Sequence[str]) -> list[list[float]]:
    if not chunks:
        return []

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=list(chunks),
        dimensions=settings.embedding_dimensions,
    )
    return [item.embedding for item in response.data]


async def upsert_embeddings(
    session: AsyncSession,
    meeting_id: UUID,
    chunks: Sequence[str],
    vectors: Sequence[Sequence[float]],
    duration_seconds: int = 0,
) -> None:
    await session.execute(delete(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting_id))

    total = max(1, len(chunks))
    duration = float(duration_seconds or total)
    if len(chunks) != len(vectors):
        raise ValueError("Chunk and embedding vector counts do not match")

    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        start_time = duration * index / total
        end_time = duration * (index + 1) / total
        session.add(
            TranscriptChunk(
                meeting_id=meeting_id,
                text=chunk,
                start_time=start_time,
                end_time=end_time,
                embedding=list(vector),
            )
        )
    await session.commit()
