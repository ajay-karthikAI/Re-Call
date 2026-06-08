import json
from uuid import UUID

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import get_settings


router = APIRouter(tags=["websocket"])


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_events(websocket: WebSocket, meeting_id: UUID) -> None:
    await websocket.accept()
    client = redis.Redis.from_url(get_settings().redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(f"meeting:{meeting_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            payload = json.loads(message["data"])
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        return
    finally:
        await pubsub.unsubscribe(f"meeting:{meeting_id}")
        await pubsub.aclose()
        await client.aclose()
