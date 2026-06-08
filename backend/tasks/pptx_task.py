import asyncio
from uuid import UUID

from database import AsyncSessionLocal
from models import Meeting, MeetingStatus
from services.events import publish_meeting_event
from services.pptx_service import generate
from services.s3_service import generate_presigned_url, upload_file
from tasks.celery_app import celery_app
from tasks.task_utils import mark_meeting_error


@celery_app.task(name="tasks.pptx_task.generate_pptx_task")
def generate_pptx_task(session_id: str) -> str:
    meeting_id = UUID(session_id)
    try:
        return asyncio.run(_generate_pptx(meeting_id))
    except Exception as error:
        asyncio.run(mark_meeting_error(meeting_id, f"Export failed: {error}"))
        raise


async def _generate_pptx(session_id: UUID) -> str:
    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None:
            raise ValueError(f"Meeting {session_id} was not found")

        output_path = await generate(session, session_id)
        s3_key = f"meetings/{session_id}/exports/notes.pptx"
        await asyncio.to_thread(upload_file, output_path, s3_key)
        meeting.pptx_s3_key = s3_key
        meeting.status = MeetingStatus.complete
        await session.commit()

        pptx_url = await asyncio.to_thread(generate_presigned_url, s3_key)

    publish_meeting_event(
        session_id,
        {"type": "complete", "session_id": str(session_id), "pptx_url": pptx_url},
    )
    return str(session_id)
