from __future__ import annotations

from pathlib import Path
import re
import textwrap
from typing import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models import Meeting
from services.chart_export_service import chart_cards_for_export, code_snippets_for_export, display_value, numeric_rows
from services.export_formatting import format_duration
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


def _chart_markdown_lines(charts: list[dict]) -> list[str]:
    if not charts:
        return []

    lines = ["## Charts", ""]
    for chart in charts:
        chart_type = chart.get("chart_type") or "chart"
        lines.extend([f"### {chart.get('title') or 'Chart'}", "", f"- Type: {chart_type}", ""])
        rows = chart.get("data") or []
        if chart_type == "needs_data":
            lines.append(chart.get("missing_data_prompt") or "Graph data missing.")
        elif chart_type == "timeline":
            lines.extend(["| Phase | Milestone |", "| --- | --- |"])
            for row in rows:
                lines.append(f"| {_markdown_table_cell(row.get('label'))} | {_markdown_table_cell(row.get('text') or display_value(row))} |")
        else:
            lines.extend(["| Label | Value | Detail |", "| --- | ---: | --- |"])
            for row in rows:
                detail = row.get("text") or row.get("owner") or row.get("severity") or ""
                lines.append(
                    f"| {_markdown_table_cell(row.get('label'))} | "
                    f"{_markdown_table_cell(display_value(row))} | "
                    f"{_markdown_table_cell(detail)} |"
                )

            bar_lines = _chart_text_bars(chart)
            if bar_lines:
                lines.extend(["", "```text", *bar_lines, "```"])

        if chart.get("insight"):
            lines.extend(["", f"Insight: {chart['insight']}"])
        lines.append("")
    return lines


def _chart_text_bars(chart: dict) -> list[str]:
    rows = numeric_rows(chart)
    if not rows:
        return []
    max_value = max(abs(float(row.get("value") or 0)) for row in rows) or 1
    labels = [str(row.get("label") or "") for row in rows]
    label_width = min(max(len(label) for label in labels), 28) if labels else 12
    bars = []
    for row in rows:
        value = abs(float(row.get("value") or 0))
        bar_width = max(1, round((value / max_value) * 24))
        label = str(row.get("label") or "")[:label_width].ljust(label_width)
        bars.append(f"{label} | {'#' * bar_width} {display_value(row)}")
    return bars


def generate_markdown(meeting: Meeting, output_path: Path) -> Path:
    notes = _notes(meeting)
    actions = notes.get("action_items") or []
    charts = chart_cards_for_export(notes, meeting.transcript or "")
    snippets = code_snippets_for_export(notes, charts)

    lines = [
        f"# {meeting.title}",
        "",
        f"- Date: {meeting.created_at:%B %d, %Y}",
        f"- Duration: {format_duration(meeting.duration_seconds)}",
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

    if charts:
        lines.extend(["", *_chart_markdown_lines(charts)])

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


def _pdf_draw_text(text: str, x: int | float, y: int | float, size: int = 10, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"0 0 0 rg BT /{font} {size} Tf {x:.1f} {y:.1f} Td ({_pdf_escape(_pdf_text(text))}) Tj ET"


def _pdf_text_page_stream(page: list[tuple[str, bool]]) -> bytes:
    commands = []
    y = 742
    for text, bold in page:
        commands.append(_pdf_draw_text(text, 54, y, 14 if bold else 10, bold))
        y -= 16
    return "\n".join(commands).encode("latin-1")


def _pdf_wrap_text(text: str, width: int = 88, **kwargs) -> list[str]:
    return textwrap.wrap(
        str(text or ""),
        width=width,
        break_long_words=True,
        break_on_hyphens=True,
        replace_whitespace=True,
        drop_whitespace=True,
        **kwargs,
    ) or [""]


def _pdf_wrapped_entries(text: str, bold: bool = False, width: int = 88) -> list[tuple[str, bool]]:
    return [(line, bold) for line in _pdf_wrap_text(text, width)]


def _pdf_wrapped_list_entries(items: Iterable, width: int = 86) -> list[tuple[str, bool]]:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        values = ["None captured"]
    lines: list[tuple[str, bool]] = []
    for item in values:
        wrapped = _pdf_wrap_text(f"- {item}", width=width, subsequent_indent="  ")
        lines.extend((line, False) for line in wrapped)
    return lines


def _pdf_chart_page_stream(chart: dict) -> bytes:
    chart_type = chart.get("chart_type") or "chart"
    commands = [
        "1 1 1 rg 0 0 612 792 re f",
        _pdf_draw_text(str(chart.get("title") or "Chart")[:70], 54, 742, 18, True),
        _pdf_draw_text(f"Type: {chart_type}", 54, 718, 10, False),
    ]
    if chart.get("insight"):
        y = 696
        for line in textwrap.wrap(str(chart["insight"]), 82)[:3]:
            commands.append(_pdf_draw_text(line, 54, y, 10, False))
            y -= 14

    if chart_type == "needs_data":
        commands.extend(_pdf_missing_chart_commands(chart))
    elif chart_type == "timeline":
        commands.extend(_pdf_timeline_commands(chart))
    elif chart_type == "table":
        commands.extend(_pdf_table_commands(chart))
    elif chart_type == "line_chart":
        commands.extend(_pdf_line_chart_commands(chart))
    else:
        commands.extend(_pdf_bar_chart_commands(chart))
    return "\n".join(commands).encode("latin-1")


def _pdf_missing_chart_commands(chart: dict) -> list[str]:
    prompt = chart.get("missing_data_prompt") or "Graph data missing."
    commands = [
        "0.96 0.97 0.96 rg 54 600 504 70 re f",
        _pdf_draw_text("Graph data missing", 76, 638, 14, True),
    ]
    y = 616
    for line in textwrap.wrap(str(prompt), 78)[:3]:
        commands.append(_pdf_draw_text(line, 76, y, 10, False))
        y -= 14
    return commands


def _pdf_tick_values(min_value: float, max_value: float) -> list[float]:
    low = min(min_value, 0)
    high = max(max_value, 1)
    if low == high:
        high = low + 1
    return [low, low + (high - low) / 2, high]


def _pdf_format_axis_value(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _pdf_bar_chart_commands(chart: dict) -> list[str]:
    rows = numeric_rows(chart)
    if not rows:
        return [_pdf_draw_text("No chart data available.", 54, 650, 11, False)]
    max_value = max(abs(float(row.get("value") or 0)) for row in rows) or 1
    x0, y0, width, height = 210, 205, 320, 445
    ticks = _pdf_tick_values(0, max_value)
    commands = [
        "0.97 0.98 0.96 rg 198 180 350 500 re f",
        "0.84 0.88 0.82 RG 1 w 198 180 350 500 re S",
        "0.84 0.88 0.82 RG 1.2 w",
        f"{x0} {y0} m {x0 + width} {y0} l S",
    ]
    for tick in ticks:
        x = x0 + (tick / max_value) * width
        commands.append("0.88 0.91 0.86 RG 0.6 w %.1f %.1f m %.1f %.1f l S" % (x, y0, x, y0 + height))
        commands.append(_pdf_draw_text(_pdf_format_axis_value(tick), x - 12, y0 - 18, 8, False))
    y = y0 + height - 34
    for row in rows[:8]:
        value = abs(float(row.get("value") or 0))
        bar_width = max(10, (value / max_value) * width)
        label = str(row.get("label") or "")[:28]
        commands.append(_pdf_draw_text(label, 54, y + 3, 9, False))
        commands.append("0.91 0.94 0.90 rg %.1f %.1f %.1f 18 re f" % (x0, y, width))
        commands.append("0.33 0.72 0.38 rg %.1f %.1f %.1f 18 re f" % (x0, y, bar_width))
        commands.append(_pdf_draw_text(display_value(row), min(x0 + bar_width + 8, x0 + width - 34), y + 5, 9, True))
        y -= 42
    if chart.get("y_label"):
        commands.append(_pdf_draw_text(str(chart["y_label"])[:24], 54, y0 + height + 18, 9, True))
    if chart.get("x_label"):
        commands.append(_pdf_draw_text(str(chart["x_label"])[:24], x0 + width - 36, y0 - 40, 9, False))
    return commands


def _pdf_line_chart_commands(chart: dict) -> list[str]:
    rows = numeric_rows(chart)
    if not rows:
        return [_pdf_draw_text("No chart data available.", 54, 650, 11, False)]
    values = [float(row.get("value") or 0) for row in rows]
    min_value = min(min(values), 0)
    max_value = max(values) or 1
    value_range = max(max_value - min_value, 1)
    x0, y0, width, height = 92, 235, 425, 350
    ticks = _pdf_tick_values(min_value, max_value)
    commands = [
        "0.97 0.98 0.96 rg 72 205 470 425 re f",
        "0.84 0.88 0.82 RG 1 w 72 205 470 425 re S",
        "0.84 0.88 0.82 RG 1.2 w",
        f"{x0} {y0} m {x0} {y0 + height} l S",
        f"{x0} {y0} m {x0 + width} {y0} l S",
    ]
    for tick in ticks:
        y = y0 + ((tick - min_value) / value_range) * height
        commands.append("0.88 0.91 0.86 RG 0.6 w %.1f %.1f m %.1f %.1f l S" % (x0, y, x0 + width, y))
        commands.append(_pdf_draw_text(_pdf_format_axis_value(tick), 54, y - 3, 8, False))
    commands.extend(
        [
        "0.25 0.70 0.35 RG 2 w",
        ]
    )
    points = []
    for index, row in enumerate(rows):
        x = x0 + (width / 2 if len(rows) == 1 else (index / (len(rows) - 1)) * width)
        y = y0 + ((float(row.get("value") or 0) - min_value) / value_range) * height
        points.append((x, y, row))
    if points:
        path = [f"{points[0][0]:.1f} {points[0][1]:.1f} m"]
        path.extend(f"{x:.1f} {y:.1f} l" for x, y, _ in points[1:])
        path.append("S")
        commands.append(" ".join(path))
    for x, y, row in points:
        commands.append("0.25 0.70 0.35 rg %.1f %.1f 5 5 re f" % (x - 2.5, y - 2.5))
        commands.append(_pdf_draw_text(display_value(row), x - 12, min(y + 14, y0 + height + 16), 8, True))
        commands.append(_pdf_draw_text(str(row.get("label") or "")[:12], x - 16, y0 - 20, 7, False))
    if chart.get("y_label"):
        commands.append(_pdf_draw_text(str(chart["y_label"])[:24], 54, y0 + height + 28, 9, True))
    if chart.get("x_label"):
        commands.append(_pdf_draw_text(str(chart["x_label"])[:24], x0 + width - 34, y0 - 42, 9, False))
    return commands


def _pdf_timeline_commands(chart: dict) -> list[str]:
    rows = chart.get("data") or []
    if not rows:
        return [_pdf_draw_text("No timeline data available.", 54, 650, 11, False)]
    commands = ["0.75 0.82 0.75 RG 2 w 92 205 m 92 650 l S"]
    y = 640
    for row in rows[:8]:
        commands.append("0.25 0.70 0.35 rg 87 %.1f 10 10 re f" % (y - 3))
        commands.append(_pdf_draw_text(str(row.get("label") or "")[:28], 116, y, 11, True))
        text_y = y - 15
        for line in textwrap.wrap(str(row.get("text") or display_value(row)), 68)[:2]:
            commands.append(_pdf_draw_text(line, 116, text_y, 9, False))
            text_y -= 12
        y -= 72
    return commands


def _pdf_table_commands(chart: dict) -> list[str]:
    rows = chart.get("data") or []
    if not rows:
        return [_pdf_draw_text("No table data available.", 54, 650, 11, False)]
    commands = [
        "0.12 0.15 0.20 rg 54 650 504 22 re f",
        _pdf_draw_text("Label", 66, 657, 10, True),
        _pdf_draw_text("Value", 330, 657, 10, True),
    ]
    y = 620
    for row in rows[:10]:
        commands.append("0.96 0.97 0.96 rg 54 %.1f 504 24 re f" % y)
        commands.append(_pdf_draw_text(str(row.get("label") or "")[:42], 66, y + 8, 9, False))
        commands.append(_pdf_draw_text(display_value(row)[:28], 330, y + 8, 9, False))
        y -= 28
    return commands


def _pdf_lines(meeting: Meeting) -> list[tuple[str, bool]]:
    notes = _notes(meeting)
    lines: list[tuple[str, bool]] = [
        (meeting.title, True),
        (f"{meeting.created_at:%B %d, %Y} | {format_duration(meeting.duration_seconds)}", False),
        ("", False),
        ("Executive Summary", True),
    ]
    lines.extend(_pdf_wrapped_entries(notes.get("summary") or "No summary was generated."))
    lines.extend([("", False), ("Insights", True)])
    lines.extend(_pdf_wrapped_list_entries(notes.get("insights") or []))
    lines.extend([("", False), ("Participants", True)])
    lines.extend(_pdf_wrapped_list_entries(notes.get("participants") or []))
    lines.extend([("", False), ("Key Decisions", True)])
    lines.extend(_pdf_wrapped_list_entries(notes.get("key_decisions") or []))
    lines.extend([("", False), ("Action Items", True)])
    for action in notes.get("action_items") or [{"owner": "TBD", "task": "No action items were captured.", "due": "TBD"}]:
        line = f"- {action.get('owner', 'TBD')}: {action.get('task', '')} (Due: {action.get('due', 'TBD')})"
        lines.extend((wrapped, False) for wrapped in _pdf_wrap_text(line, 86, subsequent_indent="  "))
    lines.extend([("", False), ("Next Steps", True)])
    for step in notes.get("next_steps") or ["None captured"]:
        lines.extend((wrapped, False) for wrapped in _pdf_wrap_text(f"- {_next_step_text(step)}", 86, subsequent_indent="  "))
    lines.extend([("", False), ("Topics Discussed", True)])
    lines.extend(_pdf_wrapped_list_entries(notes.get("topics_discussed") or []))
    lines.extend([("", False), ("Transcript", True)])
    for paragraph in (meeting.transcript or "No transcript was captured.").splitlines() or ["No transcript was captured."]:
        lines.extend(_pdf_wrapped_entries(paragraph))
    return lines


def generate_pdf(meeting: Meeting, output_path: Path) -> Path:
    page_capacity = 45
    notes = _notes(meeting)
    charts = chart_cards_for_export(notes, meeting.transcript or "")
    content_lines = _pdf_lines(meeting)
    pages = [content_lines[index : index + page_capacity] for index in range(0, len(content_lines), page_capacity)]
    if not pages:
        pages = [[("No meeting content was captured.", False)]]
    page_streams = [_pdf_text_page_stream(page) for page in pages]
    page_streams.extend(_pdf_chart_page_stream(chart) for chart in charts)

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + i * 2} 0 R' for i in range(len(page_streams)))}] /Count {len(page_streams)} >>".encode("ascii"),
    ]

    for page_index, stream in enumerate(page_streams):
        page_object_id = 3 + page_index * 2
        content_object_id = page_object_id + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >> /F2 << /Type /Font /Subtype /Type1 /BaseFont /Times-Bold >> >> >> /Contents {content_object_id} 0 R >>".encode(
                "ascii"
            )
        )
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
