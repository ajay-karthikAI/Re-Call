from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Meeting
from schemas import MeetingListResponse, MeetingResponse
from services.live_insight_service import delete_live_insights, read_live_insights
from services.live_memory_service import delete_live_memory, read_live_memory


router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.get("", response_model=MeetingListResponse)
async def list_meetings(
    limit: int = 30,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> MeetingListResponse:
    stmt = select(Meeting).order_by(desc(Meeting.created_at)).offset(offset).limit(limit)
    meetings = list((await session.scalars(stmt)).all())
    return MeetingListResponse(meetings=meetings)


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(meeting_id: UUID, session: AsyncSession = Depends(get_session)) -> Meeting:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.get("/{meeting_id}/live-memory")
async def get_live_memory(meeting_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    memory = read_live_memory(meeting_id)
    memory["live_insights"] = read_live_insights(meeting_id)
    return memory


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: UUID, session: AsyncSession = Depends(get_session)) -> None:
    await session.execute(delete(Meeting).where(Meeting.id == meeting_id))
    await session.commit()
    try:
        delete_live_memory(meeting_id)
        delete_live_insights(meeting_id)
    except Exception:
        pass
