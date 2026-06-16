from __future__ import annotations

import json
import re
from typing import Any, Optional

from openai import OpenAI

from config import get_settings


SYSTEM_PROMPT = """
You label speaker turns in computer audio from a meeting transcript.

Return ONLY a valid JSON object:
{
  "segments": [
    { "index": 0, "speaker": "Person 1" }
  ]
}

Rules:
- Use "Person 1", "Person 2", "Person 3", etc. for people heard from computer audio.
- Do not use "You"; that label is reserved for the microphone user.
- Keep the same person label consistent across turns when the language suggests the same speaker.
- Use multiple people only when the transcript reads like distinct conversational turns.
- If there is not enough evidence, keep the same Person label instead of inventing speakers.
- Do not rewrite transcript text.
""".strip()


def label_computer_speakers(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labeled_segments = [dict(segment) for segment in segments]
    candidates = [
        {
            "index": index,
            "start": round(float(segment.get("start") or 0), 2),
            "end": round(float(segment.get("end") or 0), 2),
            "text": str(segment.get("text") or "").strip(),
        }
        for index, segment in enumerate(labeled_segments)
        if str(segment.get("text") or "").strip()
    ]

    if len(candidates) < 2:
        for segment in labeled_segments:
            segment["label"] = "Person 1"
        return labeled_segments

    try:
        assignments = _speaker_assignments(candidates)
    except Exception:
        assignments = {}

    for index, segment in enumerate(labeled_segments):
        segment["label"] = assignments.get(index) or "Person 1"
    return labeled_segments


def _speaker_assignments(candidates: list[dict[str, Any]]) -> dict[int, str]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "segments": candidates,
                        "instruction": "Assign each segment to the most likely computer-audio speaker.",
                    }
                ),
            },
        ],
    )
    payload = _parse_json(response.choices[0].message.content or "{}")
    assignments: dict[int, str] = {}
    speaker_map: dict[str, str] = {}
    next_speaker_number = 1

    for item in payload.get("segments") or []:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue

        raw_speaker = str(item.get("speaker") or "").strip()
        if not raw_speaker:
            continue

        normalized = _normalize_speaker_label(raw_speaker)
        if normalized is None:
            if raw_speaker not in speaker_map:
                speaker_map[raw_speaker] = f"Person {next_speaker_number}"
                next_speaker_number += 1
            normalized = speaker_map[raw_speaker]
        assignments[index] = normalized

    return assignments


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _normalize_speaker_label(label: str) -> Optional[str]:
    match = re.search(r"(?:person|speaker)\s*(\d+)", label, flags=re.IGNORECASE)
    if not match:
        return None
    number = max(1, min(int(match.group(1)), 12))
    return f"Person {number}"
