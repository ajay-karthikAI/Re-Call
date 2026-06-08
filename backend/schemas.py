from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models import MeetingStatus


class RecordingStartResponse(BaseModel):
    session_id: UUID


class RecordingStartRequest(BaseModel):
    title: Optional[str] = None
    platform: Optional[str] = None


class RecordingStopRequest(BaseModel):
    session_id: UUID
    duration_seconds: int = 0
    capture_diagnostics: Optional[dict[str, Any]] = None


class RecordingStopResponse(BaseModel):
    session_id: UUID
    status: str


class MeetingResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    duration_seconds: int
    transcript: Optional[str]
    notes_json: Optional[dict[str, Any]]
    audio_s3_key: Optional[str]
    pptx_s3_key: Optional[str]
    is_technical: bool
    status: MeetingStatus

    model_config = ConfigDict(from_attributes=True)


class MeetingListResponse(BaseModel):
    meetings: list[MeetingResponse]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class SearchSource(BaseModel):
    meeting_title: str
    chunk_text: str
    similarity: float


class SearchResponse(BaseModel):
    answer: str
    sources: list[SearchSource]


class ExportResponse(BaseModel):
    meeting_id: UUID
    task_id: Optional[str] = None
    pptx_url: Optional[str] = None
    download_url: Optional[str] = None
    filename: Optional[str] = None
    format: Optional[str] = None
    status: str


class IntegrationConnectionResponse(BaseModel):
    provider: str
    label: str
    configured: bool
    connected: bool
    expires_at: Optional[datetime] = None
    detail: Optional[str] = None


class IntegrationConnectionsResponse(BaseModel):
    connections: list[IntegrationConnectionResponse]


class IntegrationSyncRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=180)
    limit: int = Field(default=5, ge=1, le=20)
    teams_join_url: Optional[str] = None


class IntegrationSyncResponse(BaseModel):
    provider: str
    imported_count: int
    skipped_count: int
    meetings: list[MeetingResponse]
    detail: Optional[str] = None
