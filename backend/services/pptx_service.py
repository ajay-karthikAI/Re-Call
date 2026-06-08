from datetime import datetime
from pathlib import Path
from uuid import UUID

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from sqlalchemy.ext.asyncio import AsyncSession

from models import Meeting


NAVY = RGBColor(30, 39, 97)
WHITE = RGBColor(255, 255, 255)
INK = RGBColor(20, 27, 36)
MUTED = RGBColor(93, 104, 121)
GREEN = RGBColor(0, 229, 160)
CODE_BG = RGBColor(13, 17, 23)
LIGHT = RGBColor(244, 247, 250)


def _set_bg(slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _textbox(slide, x, y, w, h, text, size=18, color=INK, bold=False, font="Calibri"):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.clear()
    paragraph = frame.paragraphs[0]
    run = paragraph.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return box


def _title(slide, text: str, dark: bool = False) -> None:
    _textbox(
        slide,
        Inches(0.7),
        Inches(0.45),
        Inches(8.6),
        Inches(0.55),
        text,
        size=32 if not dark else 40,
        color=WHITE if dark else INK,
        bold=True,
    )
    accent = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Inches(0.7), Inches(1.1), Inches(1.2), Inches(0.06))
    accent.fill.solid()
    accent.fill.fore_color.rgb = GREEN
    accent.line.fill.background()


def _add_bullets(slide, bullets: list[str], x, y, w, h, color=INK) -> None:
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.clear()
    for index, bullet in enumerate(bullets):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = bullet
        paragraph.level = 0
        paragraph.font.name = "Calibri"
        paragraph.font.size = Pt(16)
        paragraph.font.color.rgb = color
        paragraph.space_after = Pt(8)


def _summary_bullets(summary: str) -> list[str]:
    parts = [item.strip() for item in summary.replace("\n", " ").split(".") if item.strip()]
    return [f"{item}." for item in parts[:5]] or ["No summary was generated."]


def _notes(meeting: Meeting) -> dict:
    return meeting.notes_json or {}


def _next_step_text(step) -> str:
    if not isinstance(step, dict):
        return str(step)
    priority = str(step.get("priority") or "next").upper()
    task = str(step.get("task") or "Follow up")
    reason = str(step.get("reason") or "").strip()
    return f"[{priority}] {task}" + (f" - {reason}" if reason else "")


async def generate(session: AsyncSession, meeting_id: UUID) -> Path:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting {meeting_id} was not found")

    notes = _notes(meeting)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, NAVY)
    _textbox(slide, Inches(0.8), Inches(1.6), Inches(10.8), Inches(0.9), meeting.title, 40, WHITE, True)
    _textbox(
        slide,
        Inches(0.85),
        Inches(2.62),
        Inches(8.5),
        Inches(0.4),
        f"{meeting.created_at:%B %d, %Y} | {round(meeting.duration_seconds / 60, 1)} minutes",
        18,
        GREEN,
    )
    mark = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(0.85), Inches(4.55), Inches(2.2), Inches(0.56))
    mark.fill.solid()
    mark.fill.fore_color.rgb = GREEN
    mark.line.fill.background()
    _textbox(slide, Inches(1.05), Inches(4.68), Inches(1.8), Inches(0.25), "Re: Call", 16, NAVY, True)

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, WHITE)
    _title(slide, "Participants")
    participants = notes.get("participants") or ["Speaker 1"]
    for index, name in enumerate(participants[:10]):
        col = index % 2
        row = index // 2
        x = Inches(0.8 + col * 5.9)
        y = Inches(1.55 + row * 0.9)
        card = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, x, y, Inches(5.2), Inches(0.58))
        card.fill.solid()
        card.fill.fore_color.rgb = LIGHT
        card.line.color.rgb = RGBColor(224, 230, 237)
        initials = "".join(part[0] for part in str(name).split()[:2]).upper() or "S"
        circle = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.OVAL, x + Inches(0.16), y + Inches(0.11), Inches(0.36), Inches(0.36))
        circle.fill.solid()
        circle.fill.fore_color.rgb = GREEN
        circle.line.fill.background()
        _textbox(slide, x + Inches(0.235), y + Inches(0.19), Inches(0.24), Inches(0.16), initials[:2], 8, NAVY, True)
        _textbox(slide, x + Inches(0.68), y + Inches(0.17), Inches(4.0), Inches(0.25), str(name), 16, INK, True)

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, WHITE)
    _title(slide, "Executive Summary")
    quote = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.52), Inches(11.7), Inches(0.28))
    quote.fill.solid()
    quote.fill.fore_color.rgb = GREEN
    quote.line.fill.background()
    _add_bullets(slide, _summary_bullets(notes.get("summary", "")), Inches(1.0), Inches(2.0), Inches(10.8), Inches(3.6))

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, WHITE)
    _title(slide, "Insights")
    insights = notes.get("insights") or ["No insights were captured."]
    _add_bullets(slide, [str(item) for item in insights[:7]], Inches(1.0), Inches(1.65), Inches(10.8), Inches(4.5))

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, WHITE)
    _title(slide, "Key Decisions")
    decisions = notes.get("key_decisions") or ["No key decisions were captured."]
    for index, decision in enumerate(decisions[:6]):
        y = Inches(1.55 + index * 0.78)
        circle = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.OVAL, Inches(0.9), y, Inches(0.42), Inches(0.42))
        circle.fill.solid()
        circle.fill.fore_color.rgb = GREEN
        circle.line.fill.background()
        _textbox(slide, Inches(1.0), y + Inches(0.09), Inches(0.28), Inches(0.18), "OK", 8, NAVY, True)
        _textbox(slide, Inches(1.55), y + Inches(0.03), Inches(10.4), Inches(0.36), str(decision), 17, INK)

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, WHITE)
    _title(slide, "Action Items")
    actions = notes.get("action_items") or [{"owner": "TBD", "task": "No action items were captured.", "due": "TBD"}]
    table_shape = slide.shapes.add_table(len(actions[:8]) + 1, 3, Inches(0.8), Inches(1.55), Inches(11.7), Inches(4.6))
    table = table_shape.table
    widths = [2.1, 7.2, 2.4]
    for i, width in enumerate(widths):
        table.columns[i].width = Inches(width)
    for col, header in enumerate(["Owner", "Task", "Due Date"]):
        cell = table.cell(0, col)
        cell.text = header
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        cell.text_frame.paragraphs[0].runs[0].font.color.rgb = WHITE
        cell.text_frame.paragraphs[0].runs[0].font.bold = True
    for row, action in enumerate(actions[:8], start=1):
        for col, value in enumerate([action.get("owner", "TBD"), action.get("task", ""), action.get("due", "TBD")]):
            cell = table.cell(row, col)
            cell.text = str(value)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if row % 2 else LIGHT

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, WHITE)
    _title(slide, "Next Steps")
    next_steps = notes.get("next_steps") or ["No next steps were captured."]
    _add_bullets(slide, [_next_step_text(step) for step in next_steps[:7]], Inches(1.0), Inches(1.65), Inches(10.8), Inches(4.5))

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, WHITE)
    _title(slide, "Topics Covered")
    topics = notes.get("topics_discussed") or ["No topics were captured."]
    x = Inches(0.85)
    y = Inches(1.65)
    for topic in topics[:18]:
        label = str(topic)[:34]
        width = Inches(max(1.6, min(4.0, 0.18 * len(label) + 0.7)))
        if x + width > Inches(12.1):
            x = Inches(0.85)
            y += Inches(0.72)
        pill = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, x, y, width, Inches(0.42))
        pill.fill.solid()
        pill.fill.fore_color.rgb = GREEN
        pill.line.fill.background()
        _textbox(slide, x + Inches(0.18), y + Inches(0.12), width - Inches(0.32), Inches(0.16), label, 12, NAVY, True)
        x += width + Inches(0.25)

    snippets = notes.get("code_snippets") or []
    for snippet in snippets:
        slide = prs.slides.add_slide(blank)
        _set_bg(slide, CODE_BG)
        _title(slide, snippet.get("description", "Code"), dark=True)
        badge = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(0.78), Inches(1.35), Inches(1.5), Inches(0.34))
        badge.fill.solid()
        badge.fill.fore_color.rgb = GREEN
        badge.line.fill.background()
        _textbox(slide, Inches(0.96), Inches(1.45), Inches(1.1), Inches(0.12), snippet.get("language", "code"), 10, CODE_BG, True)
        code = str(snippet.get("code", ""))[:2400]
        _textbox(slide, Inches(0.85), Inches(1.9), Inches(11.8), Inches(4.85), code, 11, WHITE, False, "Courier New")

    slide = prs.slides.add_slide(blank)
    _set_bg(slide, NAVY)
    _textbox(slide, Inches(0.85), Inches(2.4), Inches(8.8), Inches(0.7), "Notes by Re: Call", 40, WHITE, True)
    _textbox(slide, Inches(0.9), Inches(3.25), Inches(5.0), Inches(0.35), datetime.now().strftime("%B %d, %Y"), 18, GREEN)
    footer_shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(5.15), Inches(3.4), Inches(0.58))
    footer_shape.fill.solid()
    footer_shape.fill.fore_color.rgb = GREEN
    footer_shape.line.fill.background()
    _textbox(slide, Inches(1.13), Inches(5.31), Inches(2.9), Inches(0.18), "Generated after the meeting", 12, NAVY, True)

    output = Path("/tmp") / f"{meeting_id}.pptx"
    prs.save(output)
    return output
