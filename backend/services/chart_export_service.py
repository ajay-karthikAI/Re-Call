from __future__ import annotations

import re
from typing import Any


SUPPORTED_CHART_TYPES = {"line_chart", "bar_chart", "table", "timeline", "needs_data"}
SEVERITY_VALUES = {"low": 1.0, "medium": 2.0, "high": 3.0}
GRAPH_CODE_PATTERN = re.compile(
    r"\b(matplotlib|pyplot|seaborn|sns\.|plt\.|ax\.plot|ax\.bar|\.plot\(|\.bar\(|go\.Figure|px\.)",
    re.IGNORECASE,
)
GRAPH_CODE_DESCRIPTION_PATTERN = re.compile(r"\b(graph|chart|plot|visuali[sz]ation|matplotlib)\b", re.IGNORECASE)


def chart_cards_from_notes(notes: dict[str, Any], include_needs_data: bool = False, limit: int = 8) -> list[dict[str, Any]]:
    live_insights = notes.get("live_insights") if isinstance(notes, dict) else {}
    overlay_cards = live_insights.get("overlay_cards") if isinstance(live_insights, dict) else []
    if not isinstance(overlay_cards, list):
        return []

    seen = set()
    charts: list[dict[str, Any]] = []
    for item in overlay_cards:
        card = normalize_chart_card(item)
        if not card:
            continue
        if card["chart_type"] == "needs_data" and not include_needs_data:
            continue
        if card["chart_type"] != "needs_data" and not has_renderable_data(card):
            continue

        key = _normalize(card.get("request") or card.get("title") or card.get("chart_type"))
        if not key or key in seen:
            continue
        seen.add(key)
        charts.append(card)
        if len(charts) >= limit:
            break
    return charts


def chart_cards_for_export(
    notes: dict[str, Any],
    transcript: str = "",
    include_needs_data: bool = True,
    limit: int = 8,
) -> list[dict[str, Any]]:
    cards = chart_cards_from_notes(notes, include_needs_data=include_needs_data, limit=limit)
    cards.extend(_derived_chart_cards(transcript, notes, include_needs_data=include_needs_data, limit=limit))
    merged = _dedupe_export_chart_cards(cards, include_needs_data=include_needs_data, limit=limit)
    if merged:
        return merged
    if has_graph_code_snippets(notes):
        return [_missing_graph_data_card()]
    return []


def code_snippets_for_export(notes: dict[str, Any], charts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    snippets = [item for item in (notes.get("code_snippets") or []) if isinstance(item, dict)]
    if charts or has_graph_code_snippets(notes):
        return [item for item in snippets if not is_graph_code_snippet(item)]
    return snippets


def has_graph_code_snippets(notes: dict[str, Any]) -> bool:
    return any(is_graph_code_snippet(item) for item in (notes.get("code_snippets") or []) if isinstance(item, dict))


def is_graph_code_snippet(snippet: dict[str, Any]) -> bool:
    code = str(snippet.get("code") or "")
    description = str(snippet.get("description") or snippet.get("title") or "")
    language = str(snippet.get("language") or "").lower()
    if GRAPH_CODE_PATTERN.search(code):
        return True
    return language == "python" and bool(GRAPH_CODE_DESCRIPTION_PATTERN.search(description) and GRAPH_CODE_PATTERN.search(code))


def normalize_chart_card(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("type") != "chart":
        return None

    chart_type = str(value.get("chart_type") or "needs_data").strip()
    if chart_type not in SUPPORTED_CHART_TYPES:
        chart_type = "bar_chart"

    data = normalize_chart_data(value.get("data"))
    if chart_type != "needs_data" and not data:
        chart_type = "needs_data"

    return {
        "type": "chart",
        "chart_type": chart_type,
        "title": _clean_text(value.get("title")) or "Graph",
        "x_label": _clean_text(value.get("x_label")),
        "y_label": _clean_text(value.get("y_label")),
        "data": data,
        "insight": _clean_text(value.get("insight")),
        "request": _clean_text(value.get("request")),
        "missing_data_prompt": _clean_text(value.get("missing_data_prompt")),
    }


def normalize_chart_data(value: Any, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label") or item.get("name") or item.get("x") or item.get("phase") or item.get("date"))
        if not label:
            continue

        row: dict[str, Any] = {"label": label}
        severity = _clean_text(item.get("severity")).lower()
        numeric = chart_numeric_value(item)
        if numeric is not None:
            row["value"] = numeric
        if severity in SEVERITY_VALUES:
            row["severity"] = severity
            row.setdefault("value", SEVERITY_VALUES[severity])

        text = _clean_text(item.get("text") or item.get("task") or item.get("description"))
        if text:
            row["text"] = text
        owner = _clean_text(item.get("owner"))
        if owner:
            row["owner"] = owner

        if "value" in row or row.get("severity") or row.get("text") or row.get("owner"):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def has_renderable_data(card: dict[str, Any]) -> bool:
    data = card.get("data")
    if not isinstance(data, list) or not data:
        return False
    if card.get("chart_type") in {"line_chart", "bar_chart"}:
        return bool(numeric_rows(card))
    return any(_clean_text(item.get("label")) for item in data if isinstance(item, dict))


def numeric_rows(card: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in card.get("data") or []:
        if not isinstance(item, dict):
            continue
        value = chart_numeric_value(item)
        if value is None:
            continue
        rows.append({**item, "value": value})
    return rows


def chart_numeric_value(item: dict[str, Any]) -> float | None:
    raw = item.get("value")
    if isinstance(raw, (int, float)):
        return float(raw)

    parsed = _parse_human_number(raw)
    if parsed is not None:
        return parsed

    severity = _clean_text(item.get("severity") or raw).lower()
    return SEVERITY_VALUES.get(severity)


def display_value(item: dict[str, Any]) -> str:
    if item.get("severity"):
        return str(item["severity"]).title()
    if "value" in item:
        value = chart_numeric_value(item)
        if value is not None:
            return _format_number(value)
    return _clean_text(item.get("text") or item.get("owner")) or "Included"


def _derived_chart_cards(
    transcript: str,
    notes: dict[str, Any],
    include_needs_data: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if not _clean_text(transcript):
        return []
    try:
        from services.overlay_chart_service import generate_deterministic_chart_cards

        memory = {
            "live_transcript": transcript,
            "summary": notes.get("summary") or "",
            "questions": _questions_from_notes(notes),
            "actions": notes.get("action_items") or [],
        }
        raw_cards = generate_deterministic_chart_cards(memory, limit=limit, transcript_max_chars=50000)
    except Exception:
        return []

    cards = []
    for raw in raw_cards:
        card = normalize_chart_card(raw)
        if not card:
            continue
        if card["chart_type"] == "needs_data" and not include_needs_data:
            continue
        if card["chart_type"] != "needs_data" and not has_renderable_data(card):
            continue
        cards.append(card)
    return cards


def _questions_from_notes(notes: dict[str, Any]) -> list[Any]:
    live_insights = notes.get("live_insights") if isinstance(notes, dict) else {}
    if isinstance(live_insights, dict):
        suggested = live_insights.get("suggested_answers")
        if isinstance(suggested, list):
            return suggested
    suggested = notes.get("suggested_answers") if isinstance(notes, dict) else []
    return suggested if isinstance(suggested, list) else []


def _dedupe_export_chart_cards(
    cards: list[dict[str, Any]],
    include_needs_data: bool,
    limit: int,
) -> list[dict[str, Any]]:
    normalized = []
    for raw in cards:
        card = normalize_chart_card(raw)
        if not card:
            continue
        if card["chart_type"] == "needs_data" and not include_needs_data:
            continue
        if card["chart_type"] != "needs_data" and not has_renderable_data(card):
            continue
        normalized.append(card)

    normalized.sort(key=lambda item: item.get("chart_type") == "needs_data")
    seen = set()
    deduped = []
    for card in normalized:
        keys = _chart_export_keys(card)
        if keys and any(key in seen for key in keys):
            continue
        seen.update(keys)
        deduped.append(card)
        if len(deduped) >= limit:
            break
    return deduped


def _chart_export_keys(card: dict[str, Any]) -> list[tuple[str, str]]:
    keys = []
    request = _normalize(card.get("request"))
    if request:
        keys.append(("request", request))

    labels = " ".join(
        _normalize(item.get("label") or "")
        for item in (card.get("data") or [])
        if isinstance(item, dict)
    )
    visual = _normalize(f"{card.get('chart_type') or ''} {card.get('title') or ''} {labels}")
    if visual:
        keys.append(("visual", visual))
    return keys


def _missing_graph_data_card() -> dict[str, Any]:
    return {
        "type": "chart",
        "chart_type": "needs_data",
        "title": "Graph data missing",
        "data": [],
        "missing_data_prompt": "A graph request was detected, but this meeting did not save structured chart data for export.",
        "request": "graph_export_missing_data",
    }


def _parse_human_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("$", "").replace(",", "").replace("%", "").lower()
    match = re.match(r"^(-?\d+(?:\.\d+)?)(k|m|b)?$", text)
    if not match:
        return None
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(match.group(2), 1)
    return float(match.group(1)) * multiplier


def _format_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}"
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s']", " ", str(value or "").lower())).strip()
