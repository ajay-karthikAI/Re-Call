from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import Meeting, TranscriptChunk
from services.embedding_service import embed_chunks

from openai import OpenAI


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
