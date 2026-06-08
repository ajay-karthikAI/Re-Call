import asyncio
from uuid import UUID

from database import AsyncSessionLocal
from models import Meeting
from services.embedding_service import chunk_text, embed_chunks, upsert_embeddings
from services.events import publish_meeting_event
from tasks.celery_app import celery_app
from tasks.task_utils import mark_meeting_error


@celery_app.task(name="tasks.embedding_task.embed_meeting_task")
def embed_meeting_task(session_id: str) -> str:
    meeting_id = UUID(session_id)
    try:
        return asyncio.run(_embed_meeting(meeting_id))
    except Exception as error:
        asyncio.run(mark_meeting_error(meeting_id, f"Embedding failed: {error}"))
        raise


async def _embed_meeting(session_id: UUID) -> str:
    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None or not meeting.transcript:
            raise ValueError(f"Meeting {session_id} has no transcript to embed")

        chunks = chunk_text(meeting.transcript)
        vectors = await asyncio.to_thread(embed_chunks, chunks)
        await upsert_embeddings(session, session_id, chunks, vectors, meeting.duration_seconds)

    publish_meeting_event(session_id, {"type": "embedded", "session_id": str(session_id)})
    return str(session_id)
