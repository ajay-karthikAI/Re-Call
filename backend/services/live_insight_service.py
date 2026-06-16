from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

import redis
from openai import OpenAI

from config import get_settings


LIVE_INSIGHT_TTL_SECONDS = 60 * 60 * 24
LIVE_INSIGHT_MIN_INTERVAL_SECONDS = 20
LIVE_INSIGHT_PROMPT = """
You are Re: Call's live meeting copilot. Given the current live meeting memory, recent transcript, and optional retrieved past-call context, return ONLY a valid JSON object.

Schema:
{
  "live_summary": "1-3 sentence live summary",
  "questions": ["important question asked or implied"],
  "risks": ["risk, blocker, objection, or ambiguity"],
  "action_items": [{ "owner": "str or TBD", "task": "str", "due": "str or TBD" }],
  "suggested_answers": [{ "question": "str", "answer": "concise suggested response", "sources": ["optional past meeting title"] }]
}

Rules:
- Be concise and useful during an active call.
- Do not invent names, facts, metrics, or decisions.
- Keep arrays short: max 5 each.
- If something is unclear, put it in risks instead of pretending certainty.
- Use retrieved past-call context only when it directly helps answer a current question.
- If retrieved context is insufficient, say what needs to be verified instead of pretending it answers the question.
- If retrieved sources are present for a "previous meeting" or "last meeting" question, use those sources as the referenced meeting context.
- Include source meeting titles in suggested_answers.sources when an answer uses retrieved context.
- Return only JSON.
""".strip()


def live_insight_keys(session_id: UUID | str) -> dict[str, str]:
    prefix = f"meeting:{session_id}"
    return {
        "insights": f"{prefix}:live_insights",
        "last_scheduled_at": f"{prefix}:live_insights:last_scheduled_at",
        "last_completed_at": f"{prefix}:live_insights:last_completed_at",
        "lock": f"{prefix}:live_insights:lock",
    }


def should_schedule_live_insights(
    client: redis.Redis,
    session_id: UUID | str,
    *,
    now: float,
    min_interval_seconds: int = LIVE_INSIGHT_MIN_INTERVAL_SECONDS,
) -> bool:
    keys = live_insight_keys(session_id)
    last_scheduled_at = _safe_float(client.get(keys["last_scheduled_at"]), 0.0)
    if now - last_scheduled_at < min_interval_seconds:
        return False
    client.setex(keys["last_scheduled_at"], LIVE_INSIGHT_TTL_SECONDS, str(now))
    return True


def mark_live_insight_complete(client: redis.Redis, session_id: UUID | str, *, now: float) -> None:
    client.setex(live_insight_keys(session_id)["last_completed_at"], LIVE_INSIGHT_TTL_SECONDS, str(now))


def acquire_live_insight_lock(client: redis.Redis, session_id: UUID | str) -> bool:
    return bool(client.set(live_insight_keys(session_id)["lock"], "1", nx=True, ex=120))


def release_live_insight_lock(client: redis.Redis, session_id: UUID | str) -> None:
    client.delete(live_insight_keys(session_id)["lock"])


def write_live_insights(client: redis.Redis, session_id: UUID | str, insights: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_live_insights(insights)
    normalized["keys"] = live_insight_keys(session_id)
    client.setex(live_insight_keys(session_id)["insights"], LIVE_INSIGHT_TTL_SECONDS, json.dumps(normalized))
    return normalized


def read_live_insights(session_id: UUID | str, client: Optional[redis.Redis] = None) -> dict[str, Any]:
    owns_client = client is None
    active_client = client or redis.Redis.from_url(get_settings().redis_url)
    try:
        raw = active_client.get(live_insight_keys(session_id)["insights"])
        parsed = _loads_json(raw, {})
        return normalize_live_insights(parsed) if isinstance(parsed, dict) else normalize_live_insights({})
    finally:
        if owns_client:
            active_client.close()


def delete_live_insights(session_id: UUID | str) -> None:
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        client.delete(*live_insight_keys(session_id).values())
    finally:
        client.close()


def generate_live_insights(memory: dict[str, Any], retrieval_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    recent_transcript = _recent_transcript(memory.get("live_transcript") or "")
    normalized_retrieval_context = normalize_retrieval_context(retrieval_context or {})
    payload = {
        "current_memory": {
            "summary": memory.get("summary") or "",
            "questions": memory.get("questions") or [],
            "actions": memory.get("actions") or [],
            "segment_count": memory.get("segment_count") or 0,
        },
        "recent_transcript": recent_transcript,
        "retrieved_past_call_context": _prompt_retrieval_context(normalized_retrieval_context),
    }
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": LIVE_INSIGHT_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    insights = normalize_live_insights(_parse_json(response.choices[0].message.content or "{}"))
    insights["retrieval_context"] = normalized_retrieval_context
    insights["suggested_answers"] = _ensure_suggested_answers(
        insights.get("suggested_answers") or [],
        normalized_retrieval_context,
    )
    return insights


def normalize_live_insights(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "live_summary": str(raw.get("live_summary") or "").strip(),
        "questions": _string_list(raw.get("questions")),
        "risks": _string_list(raw.get("risks")),
        "action_items": _action_items(raw.get("action_items")),
        "suggested_answers": _suggested_answers(raw.get("suggested_answers")),
        "overlay_cards": _overlay_cards(raw.get("overlay_cards")),
        "overlay_errors": _string_list(raw.get("overlay_errors")),
        "retrieval_context": normalize_retrieval_context(raw.get("retrieval_context") or {}),
    }


def normalize_retrieval_context(raw: dict[str, Any]) -> dict[str, Any]:
    queries = []
    if isinstance(raw.get("queries"), list):
        for item in raw["queries"][:3]:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            sources = _retrieval_sources(item.get("sources"))
            if question or sources:
                queries.append({"question": question, "sources": sources})
    return {
        "enabled": bool(raw.get("enabled", False)),
        "source": str(raw.get("source") or "past_meetings_pgvector"),
        "source_count": int(raw.get("source_count") or sum(len(item["sources"]) for item in queries)),
        "queries": queries,
        "error": str(raw.get("error") or "").strip(),
    }


def _recent_transcript(transcript: str, max_chars: int = 6000) -> str:
    text = str(transcript or "").strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:].lstrip()


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    return parsed if isinstance(parsed, dict) else {}


def _string_list(value: Any, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
    return items[:limit]


def _action_items(value: Any, limit: int = 5) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict):
            task = str(item.get("task") or "").strip()
            if not task:
                continue
            items.append(
                {
                    "owner": str(item.get("owner") or "TBD").strip() or "TBD",
                    "task": task,
                    "due": str(item.get("due") or "TBD").strip() or "TBD",
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                items.append({"owner": "TBD", "task": text, "due": "TBD"})
    return items[:limit]


def _suggested_answers(value: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if question and answer:
            normalized = {
                "question": question,
                "answer": answer,
                "sources": _string_list(item.get("sources"), limit=3),
            }
            for key in ("type", "trigger", "source_type", "confidence"):
                text = str(item.get(key) or "").strip()
                if text:
                    normalized[key] = text
            items.append(normalized)
    return items[:limit]


def _overlay_cards(value: Any, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cards = []
    for item in value:
        if not isinstance(item, dict):
            continue
        card_type = str(item.get("type") or "").strip()
        if card_type == "suggested_answer":
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not question or not answer:
                continue
            cards.append(
                {
                    "type": "suggested_answer",
                    "trigger": str(item.get("trigger") or "").strip() or "spoken_question",
                    "question": question,
                    "answer": answer,
                    "source_type": str(item.get("source_type") or "").strip() or "current_meeting",
                    "confidence": str(item.get("confidence") or "").strip() or "medium",
                    "sources": _string_list(item.get("sources"), limit=3),
                }
            )
            continue

        if card_type == "chart":
            chart_type = str(item.get("chart_type") or "needs_data").strip()
            title = str(item.get("title") or "Graph request detected").strip()
            data = _chart_data(item.get("data"))
            normalized = {
                "type": "chart",
                "trigger": str(item.get("trigger") or "").strip() or "spoken_graph_request",
                "source_type": str(item.get("source_type") or "").strip() or "current_meeting",
                "confidence": str(item.get("confidence") or "").strip() or "low",
                "chart_type": chart_type,
                "title": title,
                "x_label": str(item.get("x_label") or "").strip(),
                "y_label": str(item.get("y_label") or "").strip(),
                "data": data,
                "insight": str(item.get("insight") or "").strip(),
                "request": str(item.get("request") or "").strip(),
            }
            if chart_type == "needs_data" or not data:
                normalized["chart_type"] = "needs_data"
                normalized["confidence"] = "low"
                normalized["data"] = []
                normalized["missing_data_prompt"] = (
                    str(item.get("missing_data_prompt") or "").strip()
                    or "I heard the graph request, but I need the underlying values before I can draw it."
                )
            cards.append(normalized)
    return cards[:limit]


def _chart_data(value: Any, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label:
            continue
        normalized: dict[str, Any] = {"label": label}
        raw_value = item.get("value")
        numeric_value = _safe_float(raw_value, None)
        if numeric_value is not None:
            normalized["value"] = numeric_value
        for key in ("text", "owner", "severity"):
            text = str(item.get(key) or "").strip()
            if text:
                normalized[key] = text
        if "value" not in normalized:
            value_text = str(raw_value or "").strip().lower()
            if value_text in {"high", "medium", "low"}:
                normalized["severity"] = value_text
        if "value" in normalized or any(key in normalized for key in ("text", "owner", "severity")):
            items.append(normalized)
    return items[:limit]


def _retrieval_sources(value: Any, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sources = []
    for item in value:
        if not isinstance(item, dict):
            continue
        meeting_title = str(item.get("meeting_title") or "").strip()
        chunk_text = str(item.get("chunk_text") or "").strip()
        if not meeting_title or not chunk_text:
            continue
        sources.append(
            {
                "meeting_id": str(item.get("meeting_id") or "").strip(),
                "meeting_title": meeting_title,
                "chunk_text": chunk_text,
                "similarity": _safe_float(item.get("similarity"), 0.0),
            }
        )
    return sources[:limit]


def _prompt_retrieval_context(retrieval_context: dict[str, Any]) -> list[dict[str, Any]]:
    prompt_items = []
    for query in retrieval_context.get("queries") or []:
        sources = []
        for source in query.get("sources") or []:
            sources.append(
                {
                    "meeting_title": source.get("meeting_title") or "",
                    "similarity": source.get("similarity") or 0,
                    "excerpt": source.get("chunk_text") or "",
                }
            )
        if sources:
            prompt_items.append({"question": query.get("question") or "", "sources": sources})
    return prompt_items


def _attach_answer_sources(
    suggested_answers: list[dict[str, Any]],
    retrieval_context: dict[str, Any],
) -> list[dict[str, Any]]:
    if not suggested_answers:
        return []
    question_sources = {
        _normalize_text(item.get("question") or ""): [
            source.get("meeting_title") or ""
            for source in item.get("sources") or []
            if source.get("meeting_title")
        ]
        for item in retrieval_context.get("queries") or []
    }
    attached = []
    for item in suggested_answers:
        sources = _string_list(item.get("sources"), limit=3)
        if not sources:
            sources = question_sources.get(_normalize_text(item.get("question") or ""), [])[:3]
        attached.append({**item, "sources": sources})
    return attached


def _ensure_suggested_answers(
    suggested_answers: list[dict[str, Any]],
    retrieval_context: dict[str, Any],
) -> list[dict[str, Any]]:
    attached = _attach_answer_sources(suggested_answers, retrieval_context)
    if attached:
        return attached

    for query in retrieval_context.get("queries") or []:
        sources = query.get("sources") or []
        if not sources:
            continue
        source_titles = [
            source.get("meeting_title") or ""
            for source in sources
            if source.get("meeting_title")
        ][:3]
        strongest = sources[0]
        excerpt = str(strongest.get("chunk_text") or "").strip()
        if len(excerpt) > 360:
            excerpt = f"{excerpt[:359].rstrip()}..."
        question = str(query.get("question") or "What does the previous meeting say?").strip()
        answer = (
            f"The closest past-call context I found is from {strongest.get('meeting_title')}. "
            f"It says: {excerpt} "
            "Use this as context, but verify the exact speaker mapping if the meeting did not explicitly label Speaker 2."
        )
        return [{"question": question, "answer": answer, "sources": source_titles}]

    return []


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _loads_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        decoded = value.decode("utf-8") if isinstance(value, bytes) else value
        return float(decoded)
    except (TypeError, ValueError, UnicodeDecodeError):
        return default
