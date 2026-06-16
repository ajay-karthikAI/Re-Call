from pathlib import Path
import time
from typing import Any, Optional
from uuid import UUID

import json
import redis.asyncio as redis
from celery import chain
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_session
from models import Meeting, MeetingStatus
from schemas import RecordingStartRequest, RecordingStartResponse, RecordingStopRequest, RecordingStopResponse
from services.live_memory_service import initialize_live_memory
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
    try:
        initialize_live_memory(meeting.id)
    except Exception:
        pass
    return RecordingStartResponse(session_id=meeting.id)


@router.post("/chunk", status_code=status.HTTP_202_ACCEPTED)
async def upload_chunk(
    session_id: UUID = Form(...),
    audio: UploadFile = File(...),
    chunk_index: Optional[int] = Form(default=None),
    start_offset_ms: Optional[float] = Form(default=None),
    end_offset_ms: Optional[float] = Form(default=None),
    client_created_at_ms: Optional[float] = Form(default=None),
    redis_client: redis.Redis = Depends(_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    meeting = await session.get(Meeting, session_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting session not found")
    if meeting.status != MeetingStatus.recording:
        raise HTTPException(status_code=409, detail="Meeting is no longer recording")

    chunk_bytes = await audio.read()
    server_chunk_index = await redis_client.rpush(f"audio:{session_id}", chunk_bytes) - 1
    await redis_client.rpush(
        f"audio_meta:{session_id}",
        json.dumps(
            _chunk_metadata(
                source="mic",
                upload=audio,
                server_chunk_index=server_chunk_index,
                client_chunk_index=chunk_index,
                start_offset_ms=start_offset_ms,
                end_offset_ms=end_offset_ms,
                client_created_at_ms=client_created_at_ms,
                size=len(chunk_bytes),
            )
        ),
    )
    transcribe_chunk_task.delay(str(session_id), int(server_chunk_index))
    return {"session_id": session_id, "chunk_index": server_chunk_index, "status": "accepted"}


@router.post("/system-chunk", status_code=status.HTTP_202_ACCEPTED)
async def upload_system_chunk(
    session_id: UUID = Form(...),
    audio: UploadFile = File(...),
    chunk_index: Optional[int] = Form(default=None),
    start_offset_ms: Optional[float] = Form(default=None),
    end_offset_ms: Optional[float] = Form(default=None),
    client_created_at_ms: Optional[float] = Form(default=None),
    rms: Optional[float] = Form(default=None),
    peak: Optional[float] = Form(default=None),
    duration_seconds: Optional[float] = Form(default=None),
    silent: Optional[bool] = Form(default=None),
    redis_client: redis.Redis = Depends(_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    meeting = await session.get(Meeting, session_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting session not found")
    if meeting.status != MeetingStatus.recording:
        raise HTTPException(status_code=409, detail="Meeting is no longer recording")

    chunk_bytes = await audio.read()
    server_chunk_index = await redis_client.rpush(f"system_audio:{session_id}", chunk_bytes) - 1
    await redis_client.rpush(
        f"system_audio_meta:{session_id}",
        json.dumps(
            _chunk_metadata(
                source="system",
                upload=audio,
                server_chunk_index=server_chunk_index,
                client_chunk_index=chunk_index,
                start_offset_ms=start_offset_ms,
                end_offset_ms=end_offset_ms,
                client_created_at_ms=client_created_at_ms,
                size=len(chunk_bytes),
                rms=rms,
                peak=peak,
                duration_seconds=duration_seconds,
                silent=silent,
            )
        ),
    )
    transcribe_chunk_task.delay(str(session_id), int(server_chunk_index), "system")
    return {"session_id": session_id, "chunk_index": server_chunk_index, "bytes": len(chunk_bytes), "status": "accepted"}


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
    audio_meta = await redis_client.lrange(f"audio_meta:{payload.session_id}", 0, -1)
    if not chunks:
        raise HTTPException(status_code=400, detail="No audio chunks were uploaded")

    local_path = Path("/tmp") / f"{payload.session_id}.webm"
    with local_path.open("wb") as output:
        for chunk in chunks:
            output.write(chunk)

    s3_key = f"meetings/{payload.session_id}/audio.webm"
    upload_file(local_path, s3_key)

    system_chunks = await redis_client.lrange(f"system_audio:{payload.session_id}", 0, -1)
    system_meta = await redis_client.lrange(f"system_audio_meta:{payload.session_id}", 0, -1)
    system_audio_keys = _upload_system_audio_chunks(payload.session_id, system_chunks, system_meta)
    mic_chunk_metadata = _decode_metadata_items(audio_meta)

    frontend_diagnostics = payload.capture_diagnostics if isinstance(payload.capture_diagnostics, dict) else {}
    system_bytes = sum(len(chunk) for chunk in system_chunks)
    meeting.notes_json = {
        **(meeting.notes_json if isinstance(meeting.notes_json, dict) else {}),
        **({"system_audio_keys": system_audio_keys} if system_audio_keys else {}),
        **({"mic_chunk_metadata": mic_chunk_metadata} if mic_chunk_metadata else {}),
        "capture_diagnostics": {
            **frontend_diagnostics,
            "mode": "mic-plus-system-experimental" if system_audio_keys else "mic-only-mediarecorder",
            "chunks": len(chunks),
            "bytes": local_path.stat().st_size if local_path.exists() else 0,
            "system_audio_chunks": len(system_chunks),
            "system_audio_bytes": system_bytes,
            "system_audio_captured": bool(system_audio_keys),
            "requested_duration_seconds": payload.duration_seconds,
        },
    }

    meeting.audio_s3_key = s3_key
    meeting.duration_seconds = payload.duration_seconds
    meeting.status = MeetingStatus.transcribing
    await session.commit()
    await redis_client.delete(f"audio:{payload.session_id}")
    await redis_client.delete(f"audio_meta:{payload.session_id}")
    await redis_client.delete(f"system_audio:{payload.session_id}")
    await redis_client.delete(f"system_audio_meta:{payload.session_id}")

    _start_transcription_pipeline(payload.session_id)

    return RecordingStopResponse(session_id=payload.session_id, status="processing")


def _chunk_metadata(
    *,
    source: str,
    upload: UploadFile,
    server_chunk_index: int,
    client_chunk_index: Optional[int],
    start_offset_ms: Optional[float],
    end_offset_ms: Optional[float],
    client_created_at_ms: Optional[float],
    size: int,
    rms: Optional[float] = None,
    peak: Optional[float] = None,
    duration_seconds: Optional[float] = None,
    silent: Optional[bool] = None,
) -> dict[str, Any]:
    metadata = {
        "source": source,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "size": size,
        "server_chunk_index": server_chunk_index,
        "chunk_index": client_chunk_index if client_chunk_index is not None else server_chunk_index,
        "start_offset_ms": _safe_float(start_offset_ms),
        "end_offset_ms": _safe_float(end_offset_ms),
        "client_created_at_ms": _safe_float(client_created_at_ms),
        "server_received_at_ms": round(time.time() * 1000),
    }
    if rms is not None:
        metadata["rms"] = _safe_float(rms)
    if peak is not None:
        metadata["peak"] = _safe_float(peak)
    if duration_seconds is not None:
        metadata["duration_seconds"] = _safe_float(duration_seconds)
    if silent is not None:
        metadata["silent"] = bool(silent)
    return metadata


def _safe_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _decode_metadata_items(meta_items: list[bytes]) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []
    for item in meta_items:
        try:
            raw = item.decode("utf-8") if isinstance(item, bytes) else str(item)
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            metadata.append(parsed)
    return metadata


def _upload_system_audio_chunks(session_id: UUID, chunks: list[bytes], meta_items: list[bytes]) -> list[dict]:
    keys = []
    for index, chunk in enumerate(chunks):
        metadata = _decode_metadata_item(meta_items[index] if index < len(meta_items) else None) or {}
        extension = _extension_for_metadata(metadata) or ".m4a"
        local_path = Path("/tmp") / f"{session_id}-system-{index}{extension}"
        local_path.write_bytes(chunk)
        key = f"meetings/{session_id}/system-audio-{index}{extension}"
        upload_file(local_path, key)
        keys.append(
            {
                "source": "system",
                "key": key,
                "chunk_index": _safe_int(metadata.get("chunk_index"), index),
                "server_chunk_index": _safe_int(metadata.get("server_chunk_index"), index),
                "bytes": len(chunk),
                "start_offset_ms": _safe_float(metadata.get("start_offset_ms")),
                "end_offset_ms": _safe_float(metadata.get("end_offset_ms")),
                "client_created_at_ms": _safe_float(metadata.get("client_created_at_ms")),
                "server_received_at_ms": _safe_float(metadata.get("server_received_at_ms")),
                "rms": _safe_float(metadata.get("rms")),
                "peak": _safe_float(metadata.get("peak")),
                "duration_seconds": _safe_float(metadata.get("duration_seconds")),
                "silent": _safe_bool(metadata.get("silent")),
            }
        )
    return keys


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _extension_for_meta(meta_item: Optional[bytes]) -> Optional[str]:
    metadata = _decode_metadata_item(meta_item)
    if not metadata:
        return None
    return _extension_for_metadata(metadata)


def _decode_metadata_item(meta_item: Optional[bytes]) -> Optional[dict[str, Any]]:
    if not meta_item:
        return None
    try:
        raw = meta_item.decode("utf-8") if isinstance(meta_item, bytes) else str(meta_item)
        metadata = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None
    return metadata if isinstance(metadata, dict) else None


def _extension_for_metadata(metadata: dict[str, Any]) -> Optional[str]:
    filename = str(metadata.get("filename") or "")
    suffix = Path(filename).suffix.lower()
    if suffix in {".m4a", ".mp4", ".mp3", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm", ".flac"}:
        return suffix

    content_type = str(metadata.get("content_type") or "").lower()
    if "mp4" in content_type or "aac" in content_type:
        return ".m4a"
    if "mpeg" in content_type or "mp3" in content_type:
        return ".mp3"
    if "ogg" in content_type or "oga" in content_type:
        return ".ogg"
    if "wav" in content_type:
        return ".wav"
    if "flac" in content_type:
        return ".flac"
    if "webm" in content_type:
        return ".webm"
    return None


def _start_transcription_pipeline(session_id: UUID) -> None:
    pipeline = chain(
        transcribe_full_task.s(str(session_id)),
        analyze_meeting_task.s(),
        embed_meeting_task.s(),
        generate_pptx_task.s(),
    )
    pipeline.delay()
