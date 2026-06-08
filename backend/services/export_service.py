from __future__ import annotations

from pathlib import Path
import re
import textwrap
from typing import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models import Meeting
from services import pptx_service
from services.s3_service import generate_presigned_url, upload_file


EXPORT_CONTENT_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "markdown": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
}

EXPORT_EXTENSIONS = {
    "pptx": "pptx",
    "markdown": "md",
    "pdf": "pdf",
}


def normalize_export_format(export_format: str) -> str:
    normalized = (export_format or "pptx").lower()
    aliases = {"powerpoint": "pptx", "ppt": "pptx", "md": "markdown"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in EXPORT_EXTENSIONS:
        raise ValueError("Unsupported export format")
    return normalized


def export_filename(meeting: Meeting, export_format: str) -> str:
    title = re.sub(r"[^a-zA-Z0-9]+", "-", meeting.title.lower()).strip("-") or "meeting-notes"
    return f"{title}.{EXPORT_EXTENSIONS[export_format]}"


def export_key(meeting_id: UUID, export_format: str) -> str:
    return f"meetings/{meeting_id}/exports/notes.{EXPORT_EXTENSIONS[export_format]}"


def _notes(meeting: Meeting) -> dict:
    return meeting.notes_json if isinstance(meeting.notes_json, dict) else {}


def _list_items(items: Iterable) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"- {item}" for item in values) if values else "- None captured"


def _markdown_table_cell(value) -> str:
    return str(value or "TBD").replace("|", "\\|").replace("\n", " ")


def _next_step_text(step) -> str:
    if not isinstance(step, dict):
        return str(step)
    priority = str(step.get("priority") or "next").upper()
    task = str(step.get("task") or "Follow up")
    reason = str(step.get("reason") or "").strip()
    return f"[{priority}] {task}" + (f" - {reason}" if reason else "")


def generate_markdown(meeting: Meeting, output_path: Path) -> Path:
    notes = _notes(meeting)
    actions = notes.get("action_items") or []
    snippets = notes.get("code_snippets") or []

    lines = [
        f"# {meeting.title}",
        "",
        f"- Date: {meeting.created_at:%B %d, %Y}",
        f"- Duration: {round((meeting.duration_seconds or 0) / 60, 2)} minutes",
        f"- Status: {meeting.status.value}",
        "",
        "## Executive Summary",
        "",
        notes.get("summary") or "No summary was generated.",
        "",
        "## Insights",
        "",
        _list_items(notes.get("insights") or []),
        "",
        "## Participants",
        "",
        _list_items(notes.get("participants") or []),
        "",
        "## Key Decisions",
        "",
        _list_items(notes.get("key_decisions") or []),
        "",
        "## Action Items",
        "",
        "| Owner | Task | Due |",
        "| --- | --- | --- |",
    ]

    if actions:
        for action in actions:
            lines.append(
                f"| {_markdown_table_cell(action.get('owner'))} | "
                f"{_markdown_table_cell(action.get('task'))} | "
                f"{_markdown_table_cell(action.get('due'))} |"
            )
    else:
        lines.append("| TBD | No action items were captured. | TBD |")

    next_steps = notes.get("next_steps") or []
    lines.extend(["", "## Next Steps", ""])
    lines.append(_list_items(_next_step_text(step) for step in next_steps))

    lines.extend(
        [
            "",
            "## Topics Discussed",
            "",
            _list_items(notes.get("topics_discussed") or []),
            "",
        ]
    )

    if snippets:
        lines.extend(["## Code Snippets", ""])
        for snippet in snippets:
            language = re.sub(r"[^a-zA-Z0-9#+.-]", "", str(snippet.get("language") or "text"))
            lines.extend(
                [
                    f"### {snippet.get('description') or 'Code'}",
                    "",
                    f"```{language}",
                    str(snippet.get("code") or ""),
                    "```",
                    "",
                ]
            )

    lines.extend(["## Transcript", "", meeting.transcript or "No transcript was captured.", ""])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_text(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def _pdf_lines(meeting: Meeting) -> list[tuple[str, bool]]:
    notes = _notes(meeting)
    lines: list[tuple[str, bool]] = [
        (meeting.title, True),
        (f"{meeting.created_at:%B %d, %Y} | {round((meeting.duration_seconds or 0) / 60, 2)} minutes", False),
        ("", False),
        ("Executive Summary", True),
    ]
    lines.extend((line, False) for line in textwrap.wrap(notes.get("summary") or "No summary was generated.", 88))
    lines.extend([("", False), ("Insights", True)])
    lines.extend((f"- {item}", False) for item in (notes.get("insights") or ["None captured"]))
    lines.extend([("", False), ("Participants", True)])
    lines.extend((f"- {item}", False) for item in (notes.get("participants") or ["None captured"]))
    lines.extend([("", False), ("Key Decisions", True)])
    lines.extend((f"- {item}", False) for item in (notes.get("key_decisions") or ["None captured"]))
    lines.extend([("", False), ("Action Items", True)])
    for action in notes.get("action_items") or [{"owner": "TBD", "task": "No action items were captured.", "due": "TBD"}]:
        line = f"- {action.get('owner', 'TBD')}: {action.get('task', '')} (Due: {action.get('due', 'TBD')})"
        lines.extend((wrapped, False) for wrapped in textwrap.wrap(line, 88))
    lines.extend([("", False), ("Next Steps", True)])
    for step in notes.get("next_steps") or ["None captured"]:
        lines.extend((wrapped, False) for wrapped in textwrap.wrap(f"- {_next_step_text(step)}", 88))
    lines.extend([("", False), ("Topics Discussed", True)])
    lines.extend((f"- {item}", False) for item in (notes.get("topics_discussed") or ["None captured"]))
    lines.extend([("", False), ("Transcript", True)])
    for paragraph in (meeting.transcript or "No transcript was captured.").splitlines() or ["No transcript was captured."]:
        lines.extend((wrapped, False) for wrapped in textwrap.wrap(paragraph, 88))
    return lines


def generate_pdf(meeting: Meeting, output_path: Path) -> Path:
    page_capacity = 45
    content_lines = _pdf_lines(meeting)
    pages = [content_lines[index : index + page_capacity] for index in range(0, len(content_lines), page_capacity)]
    if not pages:
        pages = [[("No meeting content was captured.", False)]]

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + i * 2} 0 R' for i in range(len(pages)))}] /Count {len(pages)} >>".encode("ascii"),
    ]

    for page_index, page in enumerate(pages):
        page_object_id = 3 + page_index * 2
        content_object_id = page_object_id + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> /F2 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> >> >> /Contents {content_object_id} 0 R >>".encode(
                "ascii"
            )
        )
        commands = ["BT", "54 742 Td"]
        for text, bold in page:
            font = "F2" if bold else "F1"
            size = 14 if bold else 10
            commands.append(f"/{font} {size} Tf")
            commands.append(f"({_pdf_escape(_pdf_text(text))}) Tj")
            commands.append("0 -16 Td")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_id} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    output_path.write_bytes(bytes(pdf))
    return output_path


async def ensure_export(session: AsyncSession, meeting_id: UUID, export_format: str) -> tuple[str, str]:
    export_format = normalize_export_format(export_format)
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting {meeting_id} was not found")

    filename = export_filename(meeting, export_format)
    key = export_key(meeting_id, export_format)

    if export_format == "pptx" and meeting.pptx_s3_key:
        key = meeting.pptx_s3_key
    else:
        output_path = Path("/tmp") / f"{meeting_id}.{EXPORT_EXTENSIONS[export_format]}"
        if export_format == "pptx":
            output_path = await pptx_service.generate(session, meeting_id)
            key = export_key(meeting_id, "pptx")
            meeting.pptx_s3_key = key
            await session.commit()
        elif export_format == "markdown":
            generate_markdown(meeting, output_path)
        elif export_format == "pdf":
            generate_pdf(meeting, output_path)

        upload_file(output_path, key, EXPORT_CONTENT_TYPES[export_format])

    return generate_presigned_url(key, filename=filename), filename
