from __future__ import annotations

import json
import re
from typing import Any, Optional
from uuid import UUID

import redis
from openai import OpenAI

from config import get_settings


OVERLAY_ANSWER_TTL_SECONDS = 60 * 60 * 24
OVERLAY_ANSWER_PROMPT = """
You are Re: Call's in-meeting answer assistant. A spoken question was detected in the current meeting transcript.
Return ONLY a valid JSON object with this shape:
{
  "answer": "brief response the user could say out loud",
  "confidence": "high | medium | low"
}

Rules:
- Use only the current meeting context provided.
- Do not invent past-meeting facts, private data, metrics, names, or decisions.
- If the context is incomplete, give a cautious answer and say what needs confirmation.
- Keep the answer useful during a live call: 1-3 sentences.
- Confidence should be high only when the current meeting context directly supports the answer.
""".strip()


def generate_spoken_question_card(
    client: redis.Redis,
    session_id: UUID | str,
    memory: dict[str, Any],
) -> Optional[dict[str, Any]]:
    question = _latest_unseen_question(client, session_id, memory)
    if not question:
        return None

    answer = _answer_question_from_current_meeting(question, memory)
    if not answer:
        return None

    card = {
        "type": "suggested_answer",
        "trigger": "spoken_question",
        "question": question,
        "answer": answer["answer"],
        "source_type": "current_meeting",
        "confidence": answer["confidence"],
        "sources": [],
    }
    _mark_question_seen(client, session_id, question)
    return card


def merge_spoken_question_card(insights: dict[str, Any], card: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not card:
        return insights

    merged = dict(insights)
    overlay_cards = [card, *_overlay_cards(merged.get("overlay_cards"))]
    merged["overlay_cards"] = _dedupe_cards(overlay_cards)[:5]

    suggested_answers = [card, *_suggested_answers(merged.get("suggested_answers"))]
    merged["suggested_answers"] = _dedupe_answers(suggested_answers)[:5]
    return merged


def _latest_unseen_question(client: redis.Redis, session_id: UUID | str, memory: dict[str, Any]) -> str:
    questions = memory.get("questions") if isinstance(memory.get("questions"), list) else []
    for item in reversed(questions):
        question = _question_text(item)
        if not question or _is_stale_short_question(question):
            continue
        if not _question_seen(client, session_id, question):
            return question
    return ""


def _answer_question_from_current_meeting(question: str, memory: dict[str, Any]) -> Optional[dict[str, str]]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    payload = {
        "question": question,
        "current_meeting": {
            "summary": str(memory.get("summary") or ""),
            "questions": [_question_text(item) for item in (memory.get("questions") or [])][-8:],
            "actions": _action_items(memory.get("actions"))[-8:],
            "recent_transcript": _recent_transcript(memory.get("live_transcript") or ""),
        },
    }
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": OVERLAY_ANSWER_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    parsed = _parse_json(response.choices[0].message.content or "{}")
    answer = str(parsed.get("answer") or "").strip()
    confidence = str(parsed.get("confidence") or "medium").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    if not answer:
        return None
    return {"answer": answer, "confidence": confidence}


def _question_seen(client: redis.Redis, session_id: UUID | str, question: str) -> bool:
    return bool(client.sismember(_seen_key(session_id), _normalize(question)))


def _mark_question_seen(client: redis.Redis, session_id: UUID | str, question: str) -> None:
    key = _seen_key(session_id)
    client.sadd(key, _normalize(question))
    client.expire(key, OVERLAY_ANSWER_TTL_SECONDS)


def _seen_key(session_id: UUID | str) -> str:
    return f"meeting:{session_id}:overlay_answers:seen_questions"


def _question_text(item: Any) -> str:
    if isinstance(item, dict):
        return _clean_text(item.get("question") or item.get("text"))
    return _clean_text(item)


def _action_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict):
            task = _clean_text(item.get("task") or item.get("text"))
            if not task:
                continue
            items.append(
                {
                    "owner": _clean_text(item.get("owner")) or "TBD",
                    "task": task,
                    "due": _clean_text(item.get("due")) or "TBD",
                }
            )
        else:
            text = _clean_text(item)
            if text:
                items.append({"owner": "TBD", "task": text, "due": "TBD"})
    return items


def _overlay_cards(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _suggested_answers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    answers = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question = _clean_text(item.get("question"))
        answer = _clean_text(item.get("answer"))
        if question and answer:
            answers.append(item)
    return answers


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for card in cards:
        key = (str(card.get("type") or ""), _normalize(card.get("question") or card.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(card)
    return deduped


def _dedupe_answers(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for answer in answers:
        key = _normalize(answer.get("question") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(answer)
    return deduped


def _recent_transcript(transcript: str, max_chars: int = 5000) -> str:
    text = str(transcript or "").strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:].lstrip()


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _is_stale_short_question(question: str) -> bool:
    normalized = _normalize(question)
    return normalized in {"what", "why", "how", "who", "when", "where", "can we", "should we"}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s']", " ", str(value or "").lower())).strip()
