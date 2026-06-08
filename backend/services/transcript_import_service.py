from __future__ import annotations

import re
import zipfile
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree


TIMESTAMP_PATTERN = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)"
)


def _timestamp_to_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    seconds = 0.0
    for part in parts:
      seconds = seconds * 60 + float(part)
    return seconds


def _clean_line(line: str) -> str:
    text = unescape(line.strip())
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_vtt_or_srt(text: str) -> tuple[str, int]:
    lines: list[str] = []
    last_end = 0.0
    seen_text: set[str] = set()

    for raw_line in text.replace("\ufeff", "").splitlines():
        line = raw_line.strip()
        if not line or line.upper() == "WEBVTT" or line.upper().startswith("NOTE"):
            continue
        if line.isdigit():
            continue

        timestamp_match = TIMESTAMP_PATTERN.search(line)
        if timestamp_match:
            try:
                last_end = max(last_end, _timestamp_to_seconds(timestamp_match.group("end")))
            except ValueError:
                pass
            continue

        cleaned = _clean_line(line)
        if not cleaned:
            continue

        dedupe_key = cleaned.lower()
        if dedupe_key in seen_text:
            continue
        seen_text.add(dedupe_key)
        lines.append(cleaned)

    return "\n".join(lines).strip(), int(last_end)


def _parse_docx(data: bytes) -> str:
    paragraphs: list[str] = []
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    with zipfile.ZipFile(BytesIO(data)) as archive:
        document_xml = archive.read("word/document.xml")

    root = ElementTree.fromstring(document_xml)
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        cleaned = _clean_line(text)
        if cleaned:
            paragraphs.append(cleaned)

    return "\n".join(paragraphs).strip()


def normalize_transcript(raw: str) -> str:
    cleaned_lines = [_clean_line(line) for line in raw.splitlines()]
    cleaned = "\n".join(line for line in cleaned_lines if line)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def parse_transcript(
    data: bytes,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> tuple[str, int]:
    suffix = Path(filename or "").suffix.lower()
    content_type = (content_type or "").lower()

    if suffix == ".docx" or "wordprocessingml.document" in content_type:
        return _parse_docx(data), 0

    text = data.decode("utf-8-sig", errors="replace")
    if suffix in {".vtt", ".srt"} or "webvtt" in content_type or TIMESTAMP_PATTERN.search(text):
        parsed, duration_seconds = _parse_vtt_or_srt(text)
        return parsed or normalize_transcript(text), duration_seconds

    return normalize_transcript(text), 0


def provider_label(provider: str) -> str:
    normalized = provider.strip().lower()
    labels = {
        "zoom": "Zoom",
        "teams": "Microsoft Teams",
        "meet": "Google Meet",
        "manual": "Manual",
    }
    return labels.get(normalized, "Meeting")
