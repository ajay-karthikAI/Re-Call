from __future__ import annotations

import json
import re
from typing import Any, Optional
from uuid import UUID

import redis

from config import get_settings


LIVE_MEMORY_TTL_SECONDS = 60 * 60 * 24
QUESTION_STARTERS = {
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "can",
    "could",
    "should",
    "would",
    "is",
    "are",
    "do",
    "does",
    "did",
}
ACTION_PATTERNS = [
    re.compile(r"\b(action item|todo|to do|follow up|next step)\b", re.IGNORECASE),
    re.compile(r"\b(i|we|you)\s+(will|need to|should|have to|must|can)\b", re.IGNORECASE),
    re.compile(r"\b(let's|let us)\s+\w+", re.IGNORECASE),
    re.compile(r"\bplease\s+\w+", re.IGNORECASE),
]


def live_memory_keys(session_id: UUID | str) -> dict[str, str]:
    prefix = f"meeting:{session_id}"
    return {
        "live_transcript": f"{prefix}:live_transcript",
        "summary": f"{prefix}:summary",
        "questions": f"{prefix}:questions",
        "actions": f"{prefix}:actions",
        "memory": f"{prefix}:memory",
    }


def initialize_live_memory(session_id: UUID | str) -> dict[str, str]:
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        keys = live_memory_keys(session_id)
        memory = {
            "session_id": str(session_id),
            "live_transcript": "",
            "summary": "",
            "questions": [],
            "actions": [],
            "keys": keys,
        }
        pipe = client.pipeline()
        pipe.setex(keys["live_transcript"], LIVE_MEMORY_TTL_SECONDS, "")
        pipe.setex(keys["summary"], LIVE_MEMORY_TTL_SECONDS, "")
        pipe.setex(keys["questions"], LIVE_MEMORY_TTL_SECONDS, "[]")
        pipe.setex(keys["actions"], LIVE_MEMORY_TTL_SECONDS, "[]")
        pipe.setex(keys["memory"], LIVE_MEMORY_TTL_SECONDS, json.dumps(memory))
        pipe.execute()
        return keys
    finally:
        client.close()


def update_live_memory(
    client: redis.Redis,
    session_id: UUID | str,
    transcript: str,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered_segments = _ordered_segments(segments)
    questions = _extract_questions(ordered_segments)
    actions = _extract_actions(ordered_segments)
    summary = _build_live_summary(ordered_segments)
    keys = live_memory_keys(session_id)
    memory = {
        "session_id": str(session_id),
        "live_transcript": transcript,
        "summary": summary,
        "questions": questions,
        "actions": actions,
        "segment_count": len(ordered_segments),
        "keys": keys,
    }

    pipe = client.pipeline()
    pipe.setex(keys["live_transcript"], LIVE_MEMORY_TTL_SECONDS, transcript)
    pipe.setex(keys["summary"], LIVE_MEMORY_TTL_SECONDS, summary)
    pipe.setex(keys["questions"], LIVE_MEMORY_TTL_SECONDS, json.dumps(questions))
    pipe.setex(keys["actions"], LIVE_MEMORY_TTL_SECONDS, json.dumps(actions))
    pipe.setex(keys["memory"], LIVE_MEMORY_TTL_SECONDS, json.dumps(memory))
    pipe.execute()
    return memory


def read_live_memory(session_id: UUID | str, client: Optional[redis.Redis] = None) -> dict[str, Any]:
    owns_client = client is None
    active_client = client or redis.Redis.from_url(get_settings().redis_url)
    try:
        keys = live_memory_keys(session_id)
        transcript, summary, questions, actions, memory = active_client.mget(
            [
                keys["live_transcript"],
                keys["summary"],
                keys["questions"],
                keys["actions"],
                keys["memory"],
            ]
        )
        parsed_memory = _loads_json(memory, {})
        return {
            "session_id": str(session_id),
            "live_transcript": _decode_text(transcript),
            "summary": _decode_text(summary),
            "questions": _loads_json(questions, []),
            "actions": _loads_json(actions, []),
            "segment_count": parsed_memory.get("segment_count", 0) if isinstance(parsed_memory, dict) else 0,
            "keys": keys,
        }
    finally:
        if owns_client:
            active_client.close()


def delete_live_memory(session_id: UUID | str) -> None:
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        client.delete(*live_memory_keys(session_id).values())
    finally:
        client.close()


def _ordered_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(segments, key=lambda item: (_safe_float(item.get("start"), 0.0), str(item.get("source") or "")))


def _extract_questions(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions = []
    seen = set()
    for segment in segments:
        text = _clean_text(segment.get("text"))
        if not text or not _looks_like_question(text):
            continue
        normalized = _normalize(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        questions.append(_memory_item(segment, "question", text))
    return questions[-30:]


def _extract_actions(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    seen = set()
    for segment in segments:
        text = _clean_text(segment.get("text"))
        if not text or not _looks_like_action(text):
            continue
        normalized = _normalize(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        item = _memory_item(segment, "action", text)
        item["owner"] = _infer_owner(segment, text)
        item["due"] = "TBD"
        actions.append(item)
    return actions[-30:]


def _build_live_summary(segments: list[dict[str, Any]]) -> str:
    statements = []
    for segment in segments:
        text = _clean_text(segment.get("text"))
        if not text or _looks_like_question(text) or _looks_like_action(text):
            continue
        statements.append(text)

    if not statements:
        return ""

    summary = " ".join(statements[-6:])
    if len(summary) > 900:
        summary = summary[-900:].lstrip()
    return summary


def _memory_item(segment: dict[str, Any], item_type: str, text: str) -> dict[str, Any]:
    return {
        "type": item_type,
        "text": text,
        "speaker": str(segment.get("label") or "Speaker"),
        "source": str(segment.get("source") or ""),
        "start": round(_safe_float(segment.get("start"), 0.0), 2),
        "end": round(_safe_float(segment.get("end"), _safe_float(segment.get("start"), 0.0)), 2),
    }


def _looks_like_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    first_word = stripped.split(" ", 1)[0].lower().strip(".,:;!?")
    return first_word in QUESTION_STARTERS


def _looks_like_action(text: str) -> bool:
    return any(pattern.search(text) for pattern in ACTION_PATTERNS)


def _infer_owner(segment: dict[str, Any], text: str) -> str:
    label = str(segment.get("label") or "").strip()
    lowered = text.lower()
    if lowered.startswith(("i will", "i'll", "i need", "i should", "i have")) and label:
        return label
    if lowered.startswith(("you will", "you need", "you should", "can you", "could you")):
        return "You"
    if lowered.startswith(("we will", "we need", "we should", "let's", "let us")):
        return "Team"
    return label or "TBD"


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9\s']", " ", text.lower())).strip()


def _decode_text(value: Any) -> str:
    if value is None:
        return ""
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _loads_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(_decode_text(value))
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
