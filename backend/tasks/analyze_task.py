import asyncio
from uuid import UUID

from database import AsyncSessionLocal
from models import Meeting, MeetingStatus
from services.analysis_service import analyze_transcript
from services.events import publish_meeting_event
from tasks.celery_app import celery_app
from tasks.task_utils import mark_meeting_error


@celery_app.task(name="tasks.analyze_task.analyze_meeting_task")
def analyze_meeting_task(session_id: str) -> str:
    meeting_id = UUID(session_id)
    try:
        return asyncio.run(_analyze_meeting(meeting_id))
    except Exception as error:
        asyncio.run(mark_meeting_error(meeting_id, f"Analysis failed: {error}"))
        raise


async def _analyze_meeting(session_id: UUID) -> str:
    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None or not meeting.transcript:
            raise ValueError(f"Meeting {session_id} has no transcript to analyze")

        existing_notes = meeting.notes_json if isinstance(meeting.notes_json, dict) else {}
        preserved_live_notes = {
            key: existing_notes[key]
            for key in (
                "capture_diagnostics",
                "live_transcript",
                "live_memory",
                "live_insights",
                "live_insights_error",
            )
            if key in existing_notes
        }
        notes = await asyncio.to_thread(
            analyze_transcript,
            meeting.transcript,
            meeting.duration_seconds,
        )
        notes.update(preserved_live_notes)
        meeting.notes_json = notes
        meeting.title = notes.get("title") or meeting.title
        meeting.is_technical = bool(notes.get("is_technical"))
        meeting.status = MeetingStatus.analyzing
        await session.commit()

    publish_meeting_event(session_id, {"type": "analyzed", "session_id": str(session_id)})
    return str(session_id)
