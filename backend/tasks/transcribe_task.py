import asyncio
import json
from pathlib import Path
import re
from typing import Any, Optional
from uuid import UUID

import redis

from config import get_settings
from database import AsyncSessionLocal
from models import Meeting, MeetingStatus
from services.events import publish_meeting_event
from services.live_memory_service import read_live_memory, update_live_memory
from services.overlay_chart_service import generate_spoken_chart_cards, merge_chart_cards
from services.s3_service import download_file
from services.speaker_service import label_computer_speakers
from services.whisper_service import transcribe, transcribe_verbose
from tasks.celery_app import celery_app
from tasks.live_insight_task import queue_live_insights_if_due
from tasks.task_utils import mark_meeting_error


LOW_SIGNAL_RMS_THRESHOLD = 0.004
LOW_SIGNAL_PEAK_THRESHOLD = 0.025
SILENCE_HALLUCINATION_PHRASES = {
    "you",
    "thank you",
    "thanks",
    "okay",
    "ok",
    "bye",
}


@celery_app.task(name="tasks.transcribe_task.transcribe_chunk_task")
def transcribe_chunk_task(session_id: str, chunk_index: int, source: str = "mic") -> dict:
    try:
        return asyncio.run(_transcribe_live_chunk(UUID(session_id), int(chunk_index), source))
    except Exception as error:
        publish_meeting_event(
            session_id,
            {
                "type": "live_transcript_error",
                "session_id": session_id,
                "chunk_index": chunk_index,
                "source": source,
                "message": str(error),
            },
        )
        return {"session_id": session_id, "chunk_index": chunk_index, "source": source, "status": "error"}


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

        notes = dict(meeting.notes_json) if isinstance(meeting.notes_json, dict) else {}
        system_audio_keys = notes.get("system_audio_keys") if isinstance(notes.get("system_audio_keys"), list) else []
        suffix = Path(meeting.audio_s3_key).suffix or ".webm"
        local_path = Path("/tmp") / f"{session_id}{suffix}"
        download_file(meeting.audio_s3_key, local_path)

        if system_audio_keys:
            mic_result = await asyncio.to_thread(transcribe_verbose, local_path)
            mic_transcript = mic_result["text"]
            mic_segments = _source_segments(mic_result, source="mic", label="You")
        else:
            mic_transcript = await asyncio.to_thread(transcribe, local_path)
            mic_segments = []

        system_transcript = ""
        system_errors: list[str] = []
        system_segments: list[dict[str, Any]] = []
        if system_audio_keys:
            system_transcript, system_errors, system_segments = await asyncio.to_thread(
                _transcribe_system_audio,
                session_id,
                system_audio_keys,
            )
            if system_segments:
                system_segments = await asyncio.to_thread(label_computer_speakers, system_segments)

        transcript = mic_transcript
        if system_transcript:
            transcript = _format_chronological_transcript([*mic_segments, *system_segments])
            if not transcript:
                transcript = "\n\n".join(
                    [
                        f"You:\n{mic_transcript.strip()}",
                        f"Computer audio:\n{system_transcript.strip()}",
                    ]
                ).strip()
            notes["system_transcript"] = system_transcript
            notes["transcript_merge"] = {
                "mode": "time_aligned_mic_and_system",
                "mic_segments": len(mic_segments),
                "system_segments": len(system_segments),
                "computer_speaker_attribution": "text_inferred",
            }
        if system_errors:
            notes["system_transcription_errors"] = system_errors

        try:
            notes = await asyncio.to_thread(_merge_final_chart_cards, session_id, notes, transcript)
        except Exception as chart_error:
            live_insights = dict(notes.get("live_insights")) if isinstance(notes.get("live_insights"), dict) else {}
            overlay_errors = live_insights.get("overlay_errors") if isinstance(live_insights.get("overlay_errors"), list) else []
            live_insights["overlay_errors"] = [*overlay_errors, f"Final chart pass failed: {chart_error}"]
            notes["live_insights"] = live_insights

        meeting.transcript = transcript
        meeting.notes_json = notes
        meeting.status = MeetingStatus.analyzing
        await session.commit()

    publish_meeting_event(session_id, {"type": "transcribed", "session_id": str(session_id)})
    return str(session_id)


def _merge_final_chart_cards(session_id: UUID, notes: dict[str, Any], transcript: str) -> dict[str, Any]:
    memory = dict(notes.get("live_memory")) if isinstance(notes.get("live_memory"), dict) else {}
    memory["live_transcript"] = transcript
    memory.setdefault("summary", notes.get("summary", ""))
    memory.setdefault("questions", [])
    memory.setdefault("actions", notes.get("action_items", []))

    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        cards = generate_spoken_chart_cards(client, session_id, memory, ignore_seen=True)
    finally:
        client.close()

    if not cards:
        return notes

    next_notes = dict(notes)
    live_insights = dict(next_notes.get("live_insights")) if isinstance(next_notes.get("live_insights"), dict) else {}
    next_notes["live_insights"] = merge_chart_cards(live_insights, cards)
    return next_notes


async def _transcribe_live_chunk(session_id: UUID, chunk_index: int, source: str) -> dict:
    normalized_source = "system" if source == "system" else "mic"
    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None or meeting.status != MeetingStatus.recording:
            return {"session_id": str(session_id), "chunk_index": chunk_index, "source": normalized_source, "status": "skipped"}

    redis_client = redis.Redis.from_url(get_settings().redis_url)
    try:
        chunk_key = "system_audio" if normalized_source == "system" else "audio"
        meta_key = "system_audio_meta" if normalized_source == "system" else "audio_meta"
        metadata = _decode_json_bytes(redis_client.lindex(f"{meta_key}:{session_id}", chunk_index))

        if normalized_source == "mic":
            chunks = redis_client.lrange(f"{chunk_key}:{session_id}", 0, chunk_index)
            if not chunks:
                return {"session_id": str(session_id), "chunk_index": chunk_index, "source": normalized_source, "status": "missing"}
            chunk_bytes = b"".join(chunks)
            local_path = Path("/tmp") / f"{session_id}-live-{normalized_source}-through-{chunk_index}.webm"
        else:
            chunk_bytes = redis_client.lindex(f"{chunk_key}:{session_id}", chunk_index)
            if not chunk_bytes:
                return {"session_id": str(session_id), "chunk_index": chunk_index, "source": normalized_source, "status": "missing"}
            suffix = _extension_for_live_metadata(metadata, ".m4a")
            local_path = Path("/tmp") / f"{session_id}-live-{normalized_source}-{chunk_index}{suffix}"

        if normalized_source == "system" and _system_chunk_marked_silent(metadata):
            return {"session_id": str(session_id), "chunk_index": chunk_index, "source": normalized_source, "status": "silent"}

        local_path.write_bytes(chunk_bytes)

        result = await asyncio.to_thread(transcribe_verbose, local_path)
        text = result["text"].strip()
        if normalized_source == "system" and _should_drop_system_transcript(text, metadata):
            return {"session_id": str(session_id), "chunk_index": chunk_index, "source": normalized_source, "status": "filtered"}

        offset_seconds = 0.0 if normalized_source == "mic" else _source_offset_seconds(metadata, chunk_index)
        label = "Computer audio" if normalized_source == "system" else "You"
        segments = _source_segments(result, source=normalized_source, label=label, offset_seconds=offset_seconds)
        if normalized_source == "system":
            segments = [
                segment
                for segment in segments
                if not _should_drop_system_transcript(str(segment.get("text") or ""), metadata)
            ]
        if not segments:
            return {"session_id": str(session_id), "chunk_index": chunk_index, "source": normalized_source, "status": "empty"}

        live_update = await _store_live_segments(
            session_id,
            normalized_source,
            chunk_index,
            segments,
            replace_key="mic:cumulative" if normalized_source == "mic" else None,
            latest_key=f"live_transcript_latest_mic_chunk:{session_id}" if normalized_source == "mic" else None,
        )
        transcript = live_update["transcript"]
        try:
            queue_live_insights_if_due(session_id, live_update.get("memory", {}))
        except Exception:
            pass
    finally:
        redis_client.close()

    publish_meeting_event(
        session_id,
        {
            "type": "live_transcript",
            "session_id": str(session_id),
            "chunk_index": chunk_index,
            "source": normalized_source,
            "transcript": transcript,
            "memory": live_update.get("memory", {}),
        },
    )
    return {"session_id": str(session_id), "chunk_index": chunk_index, "source": normalized_source, "status": "transcribed"}


async def _store_live_segments(
    session_id: UUID,
    source: str,
    chunk_index: int,
    segments: list[dict[str, Any]],
    *,
    replace_key: Optional[str] = None,
    latest_key: Optional[str] = None,
) -> dict[str, Any]:
    redis_client = redis.Redis.from_url(get_settings().redis_url)
    try:
        key = f"live_transcript_segments:{session_id}"
        if latest_key:
            latest_chunk = _safe_int(redis_client.get(latest_key), -1)
            if chunk_index < latest_chunk:
                transcript = _format_chronological_transcript(_load_live_segments(redis_client, key))
                try:
                    memory = read_live_memory(session_id, redis_client)
                except Exception:
                    memory = {}
                return {"transcript": transcript, "memory": memory}

        redis_client.hset(key, replace_key or f"{source}:{chunk_index}", json.dumps(segments))
        if latest_key:
            redis_client.set(latest_key, chunk_index, ex=60 * 60 * 24)
        redis_client.expire(key, 60 * 60 * 24)
        stored_segments = _load_live_segments(redis_client, key)
        transcript = _format_chronological_transcript(stored_segments)
        try:
            memory = update_live_memory(redis_client, session_id, transcript, stored_segments)
        except Exception:
            memory = {}
    finally:
        redis_client.close()

    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None or meeting.status != MeetingStatus.recording:
            return {"transcript": transcript, "memory": memory}

        notes = dict(meeting.notes_json) if isinstance(meeting.notes_json, dict) else {}
        live_state = dict(notes.get("live_transcript")) if isinstance(notes.get("live_transcript"), dict) else {}
        live_state.update(
            {
                "status": "streaming",
                "mode": "best_effort_chunk_preview",
                "segment_count": len(stored_segments),
                "transcript": transcript,
            }
        )
        notes["live_transcript"] = live_state
        notes["live_memory"] = {
            "summary": memory.get("summary", ""),
            "questions": memory.get("questions", []),
            "actions": memory.get("actions", []),
            "keys": memory.get("keys", {}),
        }
        meeting.notes_json = notes
        meeting.transcript = transcript
        await session.commit()

    return {"transcript": transcript, "memory": memory}


def _load_live_segments(redis_client: redis.Redis, key: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for raw_item in redis_client.hvals(key):
        try:
            decoded = raw_item.decode("utf-8") if isinstance(raw_item, bytes) else str(raw_item)
            chunk_segments = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(chunk_segments, list):
            segments.extend(segment for segment in chunk_segments if isinstance(segment, dict))
    return segments


def _decode_json_bytes(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extension_for_live_metadata(metadata: dict[str, Any], default: str) -> str:
    filename = str(metadata.get("filename") or "")
    suffix = Path(filename).suffix.lower()
    if suffix in {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm"}:
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
    return default


def _transcribe_system_audio(session_id: UUID, system_audio_keys: list[dict]) -> tuple[str, list[str], list[dict[str, Any]]]:
    parts = []
    errors = []
    merged_segments: list[dict[str, Any]] = []

    def sort_key(item: dict) -> int:
        try:
            return int(item.get("chunk_index") or 0)
        except (TypeError, ValueError):
            return 0

    for index, source_item in enumerate(sorted(system_audio_keys, key=sort_key)):
        key = source_item.get("key")
        if not key:
            continue
        if _system_chunk_marked_silent(source_item):
            continue
        suffix = Path(key).suffix or ".m4a"
        local_path = Path("/tmp") / f"{session_id}-system-{index}{suffix}"
        try:
            download_file(key, local_path)
            result = transcribe_verbose(local_path)
            text = result["text"].strip()
            if _should_drop_system_transcript(text, source_item):
                continue
            if text:
                parts.append(text)
            segments = _source_segments(
                result,
                source="system",
                label="Computer audio",
                offset_seconds=_source_offset_seconds(source_item, index),
            )
            merged_segments.extend(
                segment
                for segment in segments
                if not _should_drop_system_transcript(str(segment.get("text") or ""), source_item)
            )
        except Exception as error:
            errors.append(f"{key}: {error}")

    return "\n".join(parts).strip(), errors, merged_segments


def _source_segments(
    transcription: dict[str, Any],
    *,
    source: str,
    label: str,
    offset_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    segments = []
    for segment in transcription.get("segments") or []:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = _safe_float(segment.get("start"), 0.0) + offset_seconds
        end = _safe_float(segment.get("end"), start) + offset_seconds
        segments.append(
            {
                "source": source,
                "label": label,
                "start": max(0.0, start),
                "end": max(0.0, end),
                "text": text,
            }
        )
    return segments


def _source_offset_seconds(source_item: dict[str, Any], index: int) -> float:
    start_offset_ms = _safe_float(source_item.get("start_offset_ms"), None)
    if start_offset_ms is not None:
        return max(0.0, start_offset_ms / 1000.0)

    end_offset_ms = _safe_float(source_item.get("end_offset_ms"), None)
    if end_offset_ms is not None:
        return max(0.0, (end_offset_ms / 1000.0) - 6.0)

    return float(index * 6)


def _system_chunk_marked_silent(source_item: dict[str, Any]) -> bool:
    return source_item.get("silent") is True


def _should_drop_system_transcript(text: str, source_item: dict[str, Any]) -> bool:
    normalized = _normalize_transcript_text(text)
    if not normalized:
        return True

    words = normalized.split()
    if words and len(words) <= 8 and all(word == "you" for word in words):
        return True

    if normalized in SILENCE_HALLUCINATION_PHRASES and _system_chunk_low_signal(source_item):
        return True

    return False


def _system_chunk_low_signal(source_item: dict[str, Any]) -> bool:
    rms = _safe_float(source_item.get("rms"), None)
    peak = _safe_float(source_item.get("peak"), None)
    if rms is None and peak is None:
        return True
    if rms is not None and rms >= LOW_SIGNAL_RMS_THRESHOLD:
        return False
    if peak is not None and peak >= LOW_SIGNAL_PEAK_THRESHOLD:
        return False
    return True


def _normalize_transcript_text(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\s']", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _format_chronological_transcript(segments: list[dict[str, Any]]) -> str:
    if not segments:
        return ""

    lines = []
    for segment in sorted(segments, key=lambda item: (_safe_float(item.get("start"), 0.0), item.get("source") != "mic")):
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        timestamp = _format_timestamp(_safe_float(segment.get("start"), 0.0))
        label = str(segment.get("label") or "Speaker")
        lines.append(f"[{timestamp}] {label}: {text}")
    return "\n".join(lines).strip()


def _format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: Optional[float]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
