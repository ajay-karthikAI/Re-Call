from __future__ import annotations

import asyncio
import time
from uuid import UUID

import redis

from config import get_settings
from database import AsyncSessionLocal
from models import Meeting
from services.events import publish_meeting_event
from services.live_insight_service import (
    acquire_live_insight_lock,
    generate_live_insights,
    mark_live_insight_complete,
    read_live_insights,
    release_live_insight_lock,
    should_schedule_live_insights,
    write_live_insights,
)
from services.live_memory_service import read_live_memory
from services.overlay_answer_service import generate_spoken_question_card, merge_spoken_question_card
from services.overlay_chart_service import generate_spoken_chart_cards, merge_chart_cards
from services.rag_service import retrieve_past_meeting_context
from tasks.celery_app import celery_app


MIN_TRANSCRIPT_CHARS_FOR_INSIGHTS = 120


def queue_live_insights_if_due(session_id: UUID | str, memory: dict) -> None:
    transcript = str(memory.get("live_transcript") or "")
    if len(transcript.strip()) < MIN_TRANSCRIPT_CHARS_FOR_INSIGHTS:
        return

    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        now = time.time()
        if not should_schedule_live_insights(client, session_id, now=now):
            return
    finally:
        client.close()

    generate_live_insights_task.delay(str(session_id))


@celery_app.task(name="tasks.live_insight_task.generate_live_insights_task")
def generate_live_insights_task(session_id: str) -> dict:
    meeting_id = UUID(session_id)
    client = redis.Redis.from_url(get_settings().redis_url)
    locked = False
    try:
        locked = acquire_live_insight_lock(client, meeting_id)
        if not locked:
            return {"session_id": session_id, "status": "locked"}

        memory = read_live_memory(meeting_id, client)
        transcript = str(memory.get("live_transcript") or "")
        if len(transcript.strip()) < MIN_TRANSCRIPT_CHARS_FOR_INSIGHTS:
            return {"session_id": session_id, "status": "too_short"}

        retrieval_context = asyncio.run(_retrieve_past_call_context(meeting_id, memory))
        insights = generate_live_insights(memory, retrieval_context)
        try:
            spoken_question_card = generate_spoken_question_card(client, meeting_id, memory)
            insights = merge_spoken_question_card(insights, spoken_question_card)
        except Exception as card_error:
            insights = {
                **insights,
                "overlay_errors": [
                    *(
                        insights.get("overlay_errors", [])
                        if isinstance(insights.get("overlay_errors"), list)
                        else []
                    ),
                    str(card_error),
                ],
            }
        try:
            spoken_chart_cards = generate_spoken_chart_cards(client, meeting_id, memory)
            insights = merge_chart_cards(insights, spoken_chart_cards)
        except Exception as chart_error:
            insights = {
                **insights,
                "overlay_errors": [
                    *(
                        insights.get("overlay_errors", [])
                        if isinstance(insights.get("overlay_errors"), list)
                        else []
                    ),
                    str(chart_error),
                ],
            }
        stored = write_live_insights(client, meeting_id, insights)
        mark_live_insight_complete(client, meeting_id, now=time.time())
        asyncio.run(_persist_live_insights(meeting_id, stored))
        publish_meeting_event(
            meeting_id,
            {
                "type": "live_insights",
                "session_id": session_id,
                "insights": stored,
            },
        )
        return {"session_id": session_id, "status": "generated"}
    except Exception as error:
        publish_meeting_event(
            meeting_id,
            {
                "type": "live_insights_error",
                "session_id": session_id,
                "message": str(error),
            },
        )
        return {"session_id": session_id, "status": "error", "message": str(error)}
    finally:
        if locked:
            release_live_insight_lock(client, meeting_id)
        client.close()


async def _persist_live_insights(session_id: UUID, insights: dict) -> None:
    async with AsyncSessionLocal() as session:
        meeting = await session.get(Meeting, session_id)
        if meeting is None:
            return

        notes = dict(meeting.notes_json) if isinstance(meeting.notes_json, dict) else {}
        notes["live_insights"] = insights
        meeting.notes_json = notes
        await session.commit()


async def _retrieve_past_call_context(session_id: UUID, memory: dict) -> dict:
    try:
        async with AsyncSessionLocal() as session:
            return await retrieve_past_meeting_context(
                session,
                session_id,
                memory.get("questions") or [],
                memory.get("live_transcript") or "",
            )
    except Exception as error:
        return {
            "enabled": True,
            "source": "past_meetings_pgvector",
            "queries": [],
            "source_count": 0,
            "error": str(error),
        }
