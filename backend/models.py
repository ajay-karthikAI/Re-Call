from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


VECTOR_DIMENSIONS = 1536


class MeetingStatus(str, enum.Enum):
    recording = "recording"
    transcribing = "transcribing"
    analyzing = "analyzing"
    complete = "complete"
    error = "error"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(240), default="Untitled call", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    notes_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    audio_s3_key: Mapped[Optional[str]] = mapped_column(String(512))
    pptx_s3_key: Mapped[Optional[str]] = mapped_column(String(512))
    is_technical: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus, name="meeting_status"),
        default=MeetingStatus.recording,
        index=True,
    )

    chunks: Mapped[list["TranscriptChunk"]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        index=True,
    )
    text: Mapped[str] = mapped_column(Text)
    start_time: Mapped[float] = mapped_column(default=0.0)
    end_time: Mapped[float] = mapped_column(default=0.0)
    embedding: Mapped[list[float]] = mapped_column(Vector(VECTOR_DIMENSIONS))

    meeting: Mapped[Meeting] = relationship(back_populates="chunks")
