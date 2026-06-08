from __future__ import annotations

import json
from uuid import UUID
from typing import Union

import redis

from config import get_settings


def publish_meeting_event(meeting_id: Union[UUID, str], payload: dict) -> None:
    client = redis.Redis.from_url(get_settings().redis_url)
    client.publish(f"meeting:{meeting_id}", json.dumps(payload, default=str))
