from __future__ import annotations

import json
import re
from typing import Any, Optional
from uuid import UUID

import redis
from openai import OpenAI

from config import get_settings


OVERLAY_CHART_TTL_SECONDS = 60 * 60 * 24
MAX_CHART_CARDS_PER_PASS = 4
MAX_STORED_OVERLAY_CARDS = 8
CHART_TYPES = {
    "line_chart",
    "bar_chart",
    "stacked_bar_chart",
    "pie_chart",
    "table",
    "timeline",
    "risk_matrix",
    "ownership_breakdown",
    "needs_data",
    "unknown",
}
GRAPH_REQUEST_PATTERN = re.compile(
    r"\b("
    r"graph|chart|plot|visuali[sz]e|trend|comparison|compare|breakdown|"
    r"timeline|risk matrix|ownership breakdown"
    r")\b",
    re.IGNORECASE,
)
GRAPH_FOLLOWUP_PATTERN = re.compile(
    r"\b(where'?s|where is|not seeing|still not seeing|supposed to make|did not make|didn't make)\b",
    re.IGNORECASE,
)
GRAPH_COMMAND_PATTERN = re.compile(
    r"\b(can you|could you|please|make|create|generate|show|build|draw|give me|turn|visuali[sz]e|chart|graph|plot)\b",
    re.IGNORECASE,
)
NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
WEEK_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
DATA_HINT_PATTERN = re.compile(
    r"(\$?\d[\d,]*(?:\.\d+)?%?|\bhigh\b|\bmedium\b|\blow\b|\bweek\s+\w+|\bq[1-4]\b|\bjan(?:uary)?\b|\bfeb(?:ruary)?\b|\bmar(?:ch)?\b|\bapr(?:il)?\b|\bmay\b|\bjun(?:e)?\b|\bjul(?:y)?\b|\baug(?:ust)?\b|\bsep(?:tember)?\b|\boct(?:ober)?\b|\bnov(?:ember)?\b|\bdec(?:ember)?\b)",
    re.IGNORECASE,
)
CHART_PROMPT = """
You are Re: Call's live chart assistant. A spoken request asked for a chart or graph during a meeting.
Return ONLY a valid JSON object.

Allowed chart_type values:
- line_chart
- bar_chart
- stacked_bar_chart
- pie_chart
- table
- timeline
- risk_matrix
- ownership_breakdown
- needs_data
- unknown

If the current transcript contains enough explicit data, return:
{
  "chart_type": "bar_chart",
  "title": "short chart title",
  "x_label": "optional axis label",
  "y_label": "optional axis label",
  "data": [
    { "label": "Week 1", "value": 12000 }
  ],
  "insight": "one concise takeaway",
  "confidence": "high | medium | low"
}

If the request asks for data that is not present in the transcript, return:
{
  "chart_type": "needs_data",
  "title": "Graph request detected",
  "data": [],
  "missing_data_prompt": "I heard the graph request, but I need ... before I can draw it.",
  "confidence": "low"
}

Rules:
- Never invent financial numbers, counts, percentages, dates, or labels.
- Extract data only from the current transcript, summary, questions, and actions provided.
- For risk severity, you may map high=3, medium=2, low=1 if those exact severity words are present.
- For ownership_breakdown, use only owners/tasks present in actions or transcript.
- For timeline, use only explicit dates/phases/order from transcript.
- If unsure or missing values, choose needs_data.
- Keep data compact: max 8 items.
""".strip()


def generate_spoken_chart_card(
    client: redis.Redis,
    session_id: UUID | str,
    memory: dict[str, Any],
) -> Optional[dict[str, Any]]:
    cards = generate_spoken_chart_cards(client, session_id, memory, limit=1)
    return cards[0] if cards else None


def generate_spoken_chart_cards(
    client: redis.Redis,
    session_id: UUID | str,
    memory: dict[str, Any],
    limit: int = MAX_CHART_CARDS_PER_PASS,
    ignore_seen: bool = False,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen_requests = set()
    seen_cards = set()
    for request in reversed(_graph_request_candidates(memory)):
        fingerprint = _request_fingerprint(request)
        if not fingerprint or fingerprint in seen_requests:
            continue
        if not ignore_seen and _request_seen(client, session_id, request):
            continue
        seen_requests.add(fingerprint)
        card = _chart_card_from_current_meeting(request, memory)
        if not card:
            continue
        card_key = _chart_card_key(card)
        if card_key in seen_cards:
            if card.get("chart_type") != "needs_data":
                _mark_request_seen(client, session_id, request)
            continue
        seen_cards.add(card_key)
        cards.append(card)
        if card.get("chart_type") != "needs_data":
            _mark_request_seen(client, session_id, request)
        if len(cards) >= limit:
            break
    return cards


def generate_deterministic_chart_cards(
    memory: dict[str, Any],
    limit: int = MAX_STORED_OVERLAY_CARDS,
    transcript_max_chars: int = 50000,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen_requests = set()
    seen_cards = set()
    for request in reversed(
        _graph_request_candidates(
            memory,
            transcript_max_chars=transcript_max_chars,
            sentence_limit=None,
            candidate_limit=max(limit * 3, 10),
        )
    ):
        fingerprint = _request_fingerprint(request)
        if not fingerprint or fingerprint in seen_requests:
            continue
        seen_requests.add(fingerprint)

        card = _deterministic_chart_card(
            request,
            memory,
            transcript_max_chars=transcript_max_chars,
            sentence_limit=None,
        )
        if not card:
            continue
        card_key = _chart_card_key(card)
        if card_key in seen_cards:
            continue
        seen_cards.add(card_key)
        cards.append(card)
        if len(cards) >= limit:
            break
    return cards


def merge_chart_card(insights: dict[str, Any], card: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not card:
        return insights
    return merge_chart_cards(insights, [card])


def merge_chart_cards(insights: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, Any]:
    if not cards:
        return insights
    merged = dict(insights)
    merged["overlay_cards"] = _dedupe_cards([*cards, *_overlay_cards(merged.get("overlay_cards"))])[:MAX_STORED_OVERLAY_CARDS]
    return merged


def _next_unseen_graph_request(client: redis.Redis, session_id: UUID | str, memory: dict[str, Any]) -> str:
    candidates = _graph_request_candidates(memory)
    for request in reversed(candidates):
        if not _request_seen(client, session_id, request):
            return request
    return ""


def _graph_request_candidates(
    memory: dict[str, Any],
    transcript_max_chars: int = 5000,
    sentence_limit: int | None = 20,
    candidate_limit: int | None = 10,
) -> list[str]:
    candidates = []
    seen = set()

    for item in memory.get("questions") or []:
        text = _item_text(item)
        if _looks_like_graph_request(text):
            key = _request_fingerprint(text)
            if key not in seen:
                seen.add(key)
                candidates.append(text)

    for text in _recent_sentences(
        memory.get("live_transcript") or "",
        max_chars=transcript_max_chars,
        sentence_limit=sentence_limit,
    ):
        if _looks_like_graph_request(text):
            key = _request_fingerprint(text)
            if key not in seen:
                seen.add(key)
                candidates.append(text)

    return candidates[-candidate_limit:] if candidate_limit else candidates


def _chart_card_from_current_meeting(request: str, memory: dict[str, Any]) -> Optional[dict[str, Any]]:
    deterministic = _deterministic_chart_card(request, memory)
    if deterministic:
        return deterministic

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    payload = {
        "spoken_request": request,
        "current_meeting": {
            "summary": str(memory.get("summary") or ""),
            "questions": [_item_text(item) for item in (memory.get("questions") or [])][-10:],
            "actions": _action_items(memory.get("actions"))[-10:],
            "recent_transcript": _recent_transcript(memory.get("live_transcript") or ""),
            "data_hint_present": bool(DATA_HINT_PATTERN.search(str(memory.get("live_transcript") or ""))),
        },
    }
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CHART_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    parsed = _parse_json(response.choices[0].message.content or "{}")
    return _normalize_chart_card(parsed, request)


def _deterministic_chart_card(
    request: str,
    memory: dict[str, Any],
    transcript_max_chars: int = 6000,
    sentence_limit: int | None = 20,
) -> Optional[dict[str, Any]]:
    transcript = _recent_transcript(memory.get("live_transcript") or "", max_chars=transcript_max_chars)
    combined = f"{request}\n{transcript}"
    lowered = combined.lower()
    request_lowered = request.lower()

    if any(word in request_lowered for word in ("earning", "revenue", "sales", "arr", "mrr")):
        weekly_data = _extract_weekly_numeric_data(
            transcript,
            max_chars=transcript_max_chars,
            sentence_limit=sentence_limit,
        )
        if weekly_data:
            values = [item["value"] for item in weekly_data if isinstance(item.get("value"), (int, float))]
            insight = ""
            if values:
                max_item = max(weekly_data, key=lambda item: item.get("value", 0))
                direction = "increased overall" if values[-1] >= values[0] else "decreased overall"
                insight = f"The series {direction}; {max_item['label']} is the highest at {int(max_item['value']):,}."
            return {
                "type": "chart",
                "trigger": "spoken_graph_request",
                "source_type": "current_meeting",
                "confidence": "high",
                "chart_type": "line_chart",
                "title": "Weekly earnings",
                "x_label": "Week",
                "y_label": "Earnings",
                "data": weekly_data,
                "insight": insight,
                "request": request,
            }
        return _needs_data_card(
            request,
            "I heard the earnings graph request, but I need the weekly earnings values before I can draw it.",
        )

    if "timeline" in request_lowered or "rollout" in request_lowered:
        timeline_data = _extract_timeline_data(
            transcript,
            max_chars=transcript_max_chars,
            sentence_limit=sentence_limit,
        )
        if timeline_data:
            return {
                "type": "chart",
                "trigger": "spoken_graph_request",
                "source_type": "current_meeting",
                "confidence": "high",
                "chart_type": "timeline",
                "title": "Beta rollout timeline",
                "x_label": "",
                "y_label": "",
                "data": timeline_data,
                "insight": "The rollout moves from testing to beta feedback before the launch decision.",
                "request": request,
            }
        return _needs_data_card(
            request,
            "I heard the timeline request, but I need dated or ordered milestones before I can draw it.",
        )

    if "risk" in request_lowered or "severity" in request_lowered:
        risk_data = _extract_risk_severity_data(
            transcript,
            max_chars=transcript_max_chars,
            sentence_limit=sentence_limit,
        )
        if risk_data:
            return {
                "type": "chart",
                "trigger": "spoken_graph_request",
                "source_type": "current_meeting",
                "confidence": "high",
                "chart_type": "bar_chart",
                "title": "Launch risks by severity",
                "x_label": "Risk",
                "y_label": "Severity",
                "data": risk_data,
                "insight": "High-severity risks should be addressed first.",
                "request": request,
            }
        return _needs_data_card(
            request,
            "I heard the risk chart request, but I need each risk and its severity before I can draw it.",
        )

    if any(word in lowered for word in ("earning", "revenue", "sales", "arr", "mrr")):
        weekly_data = _extract_weekly_numeric_data(
            transcript,
            max_chars=transcript_max_chars,
            sentence_limit=sentence_limit,
        )
        if weekly_data:
            return {
                "type": "chart",
                "trigger": "spoken_graph_request",
                "source_type": "current_meeting",
                "confidence": "high",
                "chart_type": "line_chart",
                "title": "Weekly earnings",
                "x_label": "Week",
                "y_label": "Earnings",
                "data": weekly_data,
                "insight": "",
                "request": request,
            }

    if "timeline" in lowered or "rollout" in lowered:
        timeline_data = _extract_timeline_data(
            transcript,
            max_chars=transcript_max_chars,
            sentence_limit=sentence_limit,
        )
        if timeline_data:
            return {
                "type": "chart",
                "trigger": "spoken_graph_request",
                "source_type": "current_meeting",
                "confidence": "high",
                "chart_type": "timeline",
                "title": "Beta rollout timeline",
                "x_label": "",
                "y_label": "",
                "data": timeline_data,
                "insight": "The rollout moves from testing to beta feedback before the launch decision.",
                "request": request,
            }
        return _needs_data_card(
            request,
            "I heard the timeline request, but I need dated or ordered milestones before I can draw it.",
        )

    return None


def _needs_data_card(request: str, prompt: str) -> dict[str, Any]:
    return {
        "type": "chart",
        "trigger": "spoken_graph_request",
        "source_type": "current_meeting",
        "confidence": "low",
        "chart_type": "needs_data",
        "title": "Graph request detected",
        "data": [],
        "missing_data_prompt": prompt,
        "request": request,
    }


def _normalize_chart_card(raw: dict[str, Any], request: str) -> dict[str, Any]:
    chart_type = str(raw.get("chart_type") or "unknown").strip()
    if chart_type not in CHART_TYPES:
        chart_type = "unknown"

    data = _chart_data(raw.get("data"))
    if chart_type not in {"needs_data", "unknown"} and not data:
        chart_type = "needs_data"

    confidence = str(raw.get("confidence") or ("low" if chart_type in {"needs_data", "unknown"} else "medium")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"

    card = {
        "type": "chart",
        "trigger": "spoken_graph_request",
        "source_type": "current_meeting",
        "confidence": confidence,
        "chart_type": chart_type,
        "title": _clean_text(raw.get("title")) or "Graph request detected",
        "x_label": _clean_text(raw.get("x_label")),
        "y_label": _clean_text(raw.get("y_label")),
        "data": data[:8],
        "insight": _clean_text(raw.get("insight")),
        "request": request,
    }
    missing_data_prompt = _clean_text(raw.get("missing_data_prompt"))
    if chart_type in {"needs_data", "unknown"}:
        card["chart_type"] = "needs_data"
        card["confidence"] = "low"
        card["data"] = []
        card["missing_data_prompt"] = (
            missing_data_prompt
            or "I heard the graph request, but I need the underlying values before I can draw it."
        )
    return card


def _chart_data(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label") or item.get("name") or item.get("x") or item.get("phase") or item.get("date"))
        if not label:
            continue
        normalized: dict[str, Any] = {"label": label}
        numeric_value = _safe_float(item.get("value"))
        if numeric_value is not None:
            normalized["value"] = numeric_value
        severity = _clean_text(item.get("severity")).lower()
        if severity in {"high", "medium", "low"}:
            normalized["severity"] = severity
            normalized.setdefault("value", {"low": 1, "medium": 2, "high": 3}[severity])
        text = _clean_text(item.get("text") or item.get("task") or item.get("description"))
        if text:
            normalized["text"] = text
        owner = _clean_text(item.get("owner"))
        if owner:
            normalized["owner"] = owner
        if "value" in normalized or text or owner or severity:
            items.append(normalized)
    return items


def _extract_weekly_numeric_data(
    transcript: str,
    max_chars: int = 7000,
    sentence_limit: int | None = 20,
) -> list[dict[str, Any]]:
    items = []
    seen = set()
    for sentence in _recent_sentences(transcript, max_chars=max_chars, sentence_limit=sentence_limit):
        week_match = re.search(r"\bweek\s+(?P<week>\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", sentence, re.IGNORECASE)
        if not week_match:
            continue
        week_number = _week_number(week_match.group("week"))
        if week_number is None or week_number in seen:
            continue
        after_week = sentence[week_match.end():]
        value = _extract_money_or_number(after_week)
        if value is None:
            continue
        seen.add(week_number)
        items.append({"label": f"Week {week_number}", "value": value})
    return sorted(items, key=lambda item: int(re.search(r"\d+", item["label"]).group(0)))


def _extract_risk_severity_data(
    transcript: str,
    max_chars: int = 7000,
    sentence_limit: int | None = 20,
) -> list[dict[str, Any]]:
    severity_values = {"low": 1, "medium": 2, "high": 3}
    items = []
    seen = set()
    for sentence in _recent_sentences(transcript, max_chars=max_chars, sentence_limit=sentence_limit):
        for match in re.finditer(
            r"(?P<label>[A-Za-z][A-Za-z0-9 /&+:'’,-]{2,100}?)\s+(?:is|was|are|as)\s+(?P<severity>high|medium|low)(?:\s+risk)?\b",
            sentence,
            re.IGNORECASE,
        ):
            label = _clean_risk_label(match.group("label"))
            severity = match.group("severity").lower()
            key = _normalize(label)
            if not label or key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "label": label,
                    "severity": severity,
                    "value": severity_values[severity],
                }
            )
    return items[:8]


def _extract_timeline_data(
    transcript: str,
    max_chars: int = 7000,
    sentence_limit: int | None = 20,
) -> list[dict[str, Any]]:
    timeline_starters = (
        "today",
        "tomorrow",
        "next week",
        "the week after that",
        "by the end of the month",
        "end of the month",
    )
    items = []
    seen = set()
    for sentence in _recent_sentences(transcript, max_chars=max_chars, sentence_limit=sentence_limit):
        cleaned_sentence = re.sub(r"^(and|then|finally|also)\s+", "", sentence, flags=re.IGNORECASE).strip()
        lowered = cleaned_sentence.lower()
        starter = next((item for item in timeline_starters if lowered.startswith(item)), "")
        if not starter:
            continue
        label = {
            "today": "Today",
            "tomorrow": "Tomorrow",
            "next week": "Next week",
            "the week after that": "Week after next",
            "by the end of the month": "End of month",
            "end of the month": "End of month",
        }[starter]
        if label in seen:
            continue
        seen.add(label)
        items.append({"label": label, "text": cleaned_sentence})
    return items[:8]


def _week_number(value: str) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text.isdigit():
        return int(text)
    return WEEK_NUMBER_WORDS.get(text)


def _extract_money_or_number(text: str) -> Optional[float]:
    digit_match = re.search(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand)?\b", text, re.IGNORECASE)
    if digit_match:
        value = _safe_float(digit_match.group(1))
        if value is not None and str(digit_match.group(2) or "").lower() in {"k", "thousand"}:
            return value * 1000
        return value

    word_match = re.search(
        r"\b((?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine))?)\s+thousand\b",
        text,
        re.IGNORECASE,
    )
    if word_match:
        base = _number_words_to_int(word_match.group(1))
        if base is not None:
            return float(base * 1000)
    return None


def _number_words_to_int(text: str) -> Optional[int]:
    words = re.split(r"[\s-]+", str(text or "").lower().strip())
    total = 0
    for word in words:
        if word not in NUMBER_WORDS:
            return None
        total += NUMBER_WORDS[word]
    return total or None


def _clean_risk_label(label: str) -> str:
    text = _clean_text(label)
    text = re.sub(r"^(and|plus|also|i['’]?d say|i would say|we think|the)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(risk|severity|chart|graph)\b", "", text, flags=re.IGNORECASE)
    return _clean_text(text).strip(" ,.:;-")


def _action_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict):
            task = _clean_text(item.get("task") or item.get("text"))
            if task:
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


def _request_seen(client: redis.Redis, session_id: UUID | str, request: str) -> bool:
    return bool(client.sismember(_seen_key(session_id), _request_fingerprint(request)))


def _mark_request_seen(client: redis.Redis, session_id: UUID | str, request: str) -> None:
    key = _seen_key(session_id)
    client.sadd(key, _request_fingerprint(request))
    client.expire(key, OVERLAY_CHART_TTL_SECONDS)


def _seen_key(session_id: UUID | str) -> str:
    return f"meeting:{session_id}:overlay_charts:v2:seen_requests"


def _overlay_cards(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for card in cards:
        key = _chart_card_key(card) if card.get("type") == "chart" else (
            str(card.get("type") or ""),
            _normalize(card.get("request") or card.get("question") or card.get("title") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(card)
    return deduped


def _chart_card_key(card: dict[str, Any]) -> tuple[str, str, str]:
    chart_type = str(card.get("chart_type") or "")
    if chart_type == "needs_data":
        return ("chart", chart_type, _normalize(card.get("request") or card.get("title") or ""))
    labels = " ".join(
        _normalize(item.get("label") or "")
        for item in (card.get("data") or [])
        if isinstance(item, dict)
    )
    return ("chart", chart_type, _normalize(card.get("title") or labels or card.get("request") or ""))


def _recent_sentences(
    transcript: str,
    max_chars: int = 5000,
    sentence_limit: int | None = 20,
) -> list[str]:
    text = _recent_transcript(transcript, max_chars=max_chars)
    text = re.sub(r"\[[^\]]+\]\s*[^:]+:\s*", " ", text)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    sentences = []
    for part in parts:
        cleaned = _clean_text(_strip_speaker_prefix(part))
        if cleaned:
            sentences.append(cleaned)
    return sentences[-sentence_limit:] if sentence_limit else sentences


def _strip_speaker_prefix(text: str) -> str:
    return re.sub(
        r"^\s*(?:\[[^\]]+\]\s*)?(?:speaker|person|participant)\s*\d+\s*:\s*",
        "",
        str(text or ""),
        flags=re.IGNORECASE,
    )


def _request_fingerprint(text: str) -> str:
    for sentence in _recent_sentences(text, max_chars=1200):
        if _looks_like_graph_request(sentence):
            return _normalize(sentence)
    return _normalize(text)


def _looks_like_graph_request(text: str) -> bool:
    if not text or _looks_like_graph_followup(text) or not GRAPH_REQUEST_PATTERN.search(text):
        return False
    normalized = _normalize(text)
    if "?" in str(text) and GRAPH_COMMAND_PATTERN.search(text):
        return True
    if re.search(
        r"\b(make|create|generate|show|build|draw|give me|turn|visuali[sz]e|chart|graph|plot)\b.*\b(graph|chart|plot|timeline|breakdown|comparison|trend|risk matrix|ownership breakdown)\b",
        normalized,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(graph|chart|plot|timeline|breakdown|comparison|trend|risk matrix|ownership breakdown)\b.*\b(of|by|for|from)\b",
        normalized,
        re.IGNORECASE,
    ) and GRAPH_COMMAND_PATTERN.search(text):
        return True
    return False


def _looks_like_graph_followup(text: str) -> bool:
    return bool(text and GRAPH_FOLLOWUP_PATTERN.search(text))


def _recent_transcript(transcript: str, max_chars: int = 6000) -> str:
    text = str(transcript or "").strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:].lstrip()


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        return _clean_text(item.get("question") or item.get("text"))
    return _clean_text(item)


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


def _safe_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").replace("%", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s']", " ", str(value or "").lower())).strip()
