import json
from typing import Any

from openai import OpenAI

from config import get_settings


SYSTEM_PROMPT = """
You are Re: Call, an expert meeting analyst. Given a raw meeting transcript, return ONLY a valid JSON object - no prose, no markdown, no code fences.

Schema:
{
  "title": "descriptive meeting title",
  "duration_minutes": number,
  "participants": ["name or Speaker N"],
  "summary": "3-5 sentence executive summary",
  "insights": ["specific insight, risk, opportunity, or pattern"],
  "key_decisions": ["decision 1"],
  "action_items": [{ "owner": "str", "task": "str", "due": "str or TBD" }],
  "next_steps": [{ "priority": "high | medium | low", "task": "str", "reason": "why this matters" }],
  "topics_discussed": ["topic 1"],
  "sentiment": "productive | inconclusive | tense | informational",
  "is_technical": true or false,
  "code_snippets": [
    { "language": "str", "description": "str", "code": "clean runnable code - not verbatim spoken words" }
  ]
}

Rules:
- insights should explain what mattered beyond a plain recap
- next_steps should be concrete follow-up recommendations, not generic advice
- code_snippets only if is_technical is true
- Clean up all code into syntactically valid form
- Return only the JSON object
""".strip()


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def analyze_transcript(transcript: str, duration_seconds: int = 0) -> dict[str, Any]:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Duration seconds: {duration_seconds}\n\n"
                    f"Transcript:\n{transcript}"
                ),
            },
        ],
    )
    return _parse_json(response.choices[0].message.content or "{}")
