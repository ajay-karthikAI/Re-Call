from uuid import UUID

from database import AsyncSessionLocal
from models import Meeting, MeetingStatus
from services.events import publish_meeting_event


async def mark_meeting_error(session_id: UUID, message: str) -> None:
    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None:
            return

        notes = dict(meeting.notes_json) if isinstance(meeting.notes_json, dict) else {}
        notes["error"] = message
        meeting.notes_json = notes
        meeting.status = MeetingStatus.error
        await session.commit()

    publish_meeting_event(
        session_id,
        {"type": "error", "session_id": str(session_id), "message": message},
    )
