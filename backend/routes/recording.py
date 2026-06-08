from pathlib import Path
from typing import Optional
from uuid import UUID

import redis.asyncio as redis
from celery import chain
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_session
from models import Meeting, MeetingStatus
from schemas import RecordingStartRequest, RecordingStartResponse, RecordingStopRequest, RecordingStopResponse
from services.s3_service import upload_file
from tasks.analyze_task import analyze_meeting_task
from tasks.embedding_task import embed_meeting_task
from tasks.pptx_task import generate_pptx_task
from tasks.transcribe_task import transcribe_chunk_task, transcribe_full_task


router = APIRouter(prefix="/api/recording", tags=["recording"])


async def _redis():
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        yield client
    finally:
        await client.aclose()


@router.post("/start", response_model=RecordingStartResponse)
async def start_recording(
    payload: Optional[RecordingStartRequest] = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> RecordingStartResponse:
    title = "Untitled call"
    if payload and payload.title:
        title = payload.title.strip()[:240] or title
    if payload and payload.platform and title == "Untitled call":
        title = f"{payload.platform.strip()[:80]} call"

    meeting = Meeting(title=title, status=MeetingStatus.recording)
    session.add(meeting)
    await session.commit()
    await session.refresh(meeting)
    return RecordingStartResponse(session_id=meeting.id)


@router.post("/chunk", status_code=status.HTTP_202_ACCEPTED)
async def upload_chunk(
    session_id: UUID = Form(...),
    audio: UploadFile = File(...),
    redis_client: redis.Redis = Depends(_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    meeting = await session.get(Meeting, session_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting session not found")
    if meeting.status != MeetingStatus.recording:
        raise HTTPException(status_code=409, detail="Meeting is no longer recording")

    chunk_bytes = await audio.read()
    chunk_index = await redis_client.rpush(f"audio:{session_id}", chunk_bytes) - 1
    transcribe_chunk_task.delay(str(session_id), int(chunk_index))
    return {"session_id": session_id, "chunk_index": chunk_index, "status": "accepted"}


@router.post("/stop", response_model=RecordingStopResponse)
async def stop_recording(
    payload: RecordingStopRequest,
    redis_client: redis.Redis = Depends(_redis),
    session: AsyncSession = Depends(get_session),
) -> RecordingStopResponse:
    meeting = await session.get(Meeting, payload.session_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting session not found")

    chunks = await redis_client.lrange(f"audio:{payload.session_id}", 0, -1)
    if not chunks:
        raise HTTPException(status_code=400, detail="No audio chunks were uploaded")

    local_path = Path("/tmp") / f"{payload.session_id}.webm"
    with local_path.open("wb") as output:
        for chunk in chunks:
            output.write(chunk)

    s3_key = f"meetings/{payload.session_id}/audio.webm"
    upload_file(local_path, s3_key)

    frontend_diagnostics = payload.capture_diagnostics if isinstance(payload.capture_diagnostics, dict) else {}
    meeting.notes_json = {
        **(meeting.notes_json if isinstance(meeting.notes_json, dict) else {}),
        "capture_diagnostics": {
            **frontend_diagnostics,
            "mode": "mic-only-mediarecorder",
            "chunks": len(chunks),
            "bytes": local_path.stat().st_size if local_path.exists() else 0,
            "requested_duration_seconds": payload.duration_seconds,
        },
    }

    meeting.audio_s3_key = s3_key
    meeting.duration_seconds = payload.duration_seconds
    meeting.status = MeetingStatus.transcribing
    await session.commit()
    await redis_client.delete(f"audio:{payload.session_id}")

    _start_transcription_pipeline(payload.session_id)

    return RecordingStopResponse(session_id=payload.session_id, status="processing")


def _start_transcription_pipeline(session_id: UUID) -> None:
    pipeline = chain(
        transcribe_full_task.s(str(session_id)),
        analyze_meeting_task.s(),
        embed_meeting_task.s(),
        generate_pptx_task.s(),
    )
    pipeline.delay()
