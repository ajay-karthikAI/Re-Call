from __future__ import annotations

import json
import re
from typing import Any, Optional

from openai import OpenAI

from config import get_settings


COMPUTER_SYSTEM_PROMPT = """
You label speaker turns in computer audio from a meeting transcript.

Return ONLY a valid JSON object:
{
  "segments": [
    { "index": 0, "speaker": "Person 1" }
  ]
}

Rules:
- Use "Person 1", "Person 2", "Person 3", etc. for people heard from computer audio.
- Do not use "You"; microphone-side voices are labeled separately as Local Speaker N.
- Keep the same person label consistent across turns when the language suggests the same speaker.
- Use multiple people only when the transcript reads like distinct conversational turns.
- If there is not enough evidence, keep the same Person label instead of inventing speakers.
- Do not rewrite transcript text.
""".strip()

MICROPHONE_SYSTEM_PROMPT = """
You label speaker turns from a shared local microphone recording.

Return ONLY a valid JSON object:
{
  "segments": [
    { "index": 0, "speaker": "Local Speaker 1" }
  ]
}

Rules:
- Use only "Local Speaker 1", "Local Speaker 2", and "Local Speaker 3" for people heard through the microphone.
- Do not create more than 3 microphone speakers; map uncertain or extra voices to the closest existing Local Speaker label.
- Keep the same Local Speaker label consistent across turns when the language suggests the same speaker.
- Use multiple Local Speaker labels only when the transcript reads like distinct conversational turns.
- If there is not enough evidence, keep the same Local Speaker label instead of inventing speakers.
- Do not rewrite transcript text.
""".strip()


def label_computer_speakers(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _label_speakers(
        segments,
        system_prompt=COMPUTER_SYSTEM_PROMPT,
        instruction="Assign each segment to the most likely computer-audio speaker.",
        output_prefix="Person",
        default_label="Person 1",
        max_speakers=12,
    )


def label_microphone_speakers(segments: list[dict[str, Any]], max_speakers: int = 3) -> list[dict[str, Any]]:
    max_speakers = max(1, min(int(max_speakers), 3))
    return _label_speakers(
        segments,
        system_prompt=MICROPHONE_SYSTEM_PROMPT,
        instruction=f"Assign each segment to one of at most {max_speakers} local microphone speakers.",
        output_prefix="Local Speaker",
        default_label="Local Speaker 1",
        max_speakers=max_speakers,
    )


def _label_speakers(
    segments: list[dict[str, Any]],
    *,
    system_prompt: str,
    instruction: str,
    output_prefix: str,
    default_label: str,
    max_speakers: int,
) -> list[dict[str, Any]]:
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
            segment["label"] = default_label
        return labeled_segments

    try:
        assignments = _speaker_assignments(
            candidates,
            system_prompt=system_prompt,
            instruction=instruction,
            output_prefix=output_prefix,
            max_speakers=max_speakers,
        )
    except Exception:
        assignments = {}

    for index, segment in enumerate(labeled_segments):
        segment["label"] = assignments.get(index) or default_label
    return labeled_segments


def _speaker_assignments(
    candidates: list[dict[str, Any]],
    *,
    system_prompt: str,
    instruction: str,
    output_prefix: str,
    max_speakers: int,
) -> dict[int, str]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "segments": candidates,
                        "instruction": instruction,
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

        normalized = _normalize_speaker_label(raw_speaker, output_prefix=output_prefix, max_speakers=max_speakers)
        if normalized is None:
            if raw_speaker not in speaker_map:
                speaker_map[raw_speaker] = f"{output_prefix} {min(next_speaker_number, max_speakers)}"
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


def _normalize_speaker_label(label: str, *, output_prefix: str, max_speakers: int) -> Optional[str]:
    match = re.search(
        r"(?:local\s+speaker|local|mic(?:rophone)?(?:\s+speaker)?|person|speaker)\s*(\d+)",
        label,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    number = max(1, min(int(match.group(1)), max_speakers))
    return f"{output_prefix} {number}"
