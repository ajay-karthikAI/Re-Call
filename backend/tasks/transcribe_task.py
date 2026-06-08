import asyncio
from pathlib import Path
from uuid import UUID

from database import AsyncSessionLocal
from models import Meeting, MeetingStatus
from services.events import publish_meeting_event
from services.s3_service import download_file
from services.whisper_service import transcribe
from tasks.celery_app import celery_app
from tasks.task_utils import mark_meeting_error


@celery_app.task(name="tasks.transcribe_task.transcribe_chunk_task")
def transcribe_chunk_task(session_id: str, chunk_index: int) -> dict:
    publish_meeting_event(
        session_id,
        {"type": "chunk_accepted", "session_id": session_id, "chunk_index": chunk_index},
    )
    return {"session_id": session_id, "chunk_index": chunk_index}


@celery_app.task(name="tasks.transcribe_task.transcribe_full_task")
def transcribe_full_task(session_id: str) -> str:
    meeting_id = UUID(session_id)
    try:
        return asyncio.run(_transcribe_full(meeting_id))
    except Exception as error:
        asyncio.run(mark_meeting_error(meeting_id, f"Transcription failed: {error}"))
        raise


async def _transcribe_full(session_id: UUID) -> str:
    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None or not meeting.audio_s3_key:
            raise ValueError(f"Meeting {session_id} is missing audio")

        suffix = Path(meeting.audio_s3_key).suffix or ".webm"
        local_path = Path("/tmp") / f"{session_id}{suffix}"
        download_file(meeting.audio_s3_key, local_path)
        transcript = await asyncio.to_thread(transcribe, local_path)

        meeting.transcript = transcript
        meeting.status = MeetingStatus.analyzing
        await session.commit()

    publish_meeting_event(session_id, {"type": "transcribed", "session_id": str(session_id)})
    return str(session_id)
