"""Initial Re: Call schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


meeting_status = postgresql.ENUM(
    "recording",
    "transcribing",
    "analyzing",
    "complete",
    "error",
    name="meeting_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    meeting_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "meetings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("notes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("audio_s3_key", sa.String(length=512), nullable=True),
        sa.Column("pptx_s3_key", sa.String(length=512), nullable=True),
        sa.Column("is_technical", sa.Boolean(), nullable=False),
        sa.Column("status", meeting_status, nullable=False),
    )
    op.create_index("ix_meetings_created_at", "meetings", ["created_at"])
    op.create_index("ix_meetings_status", "meetings", ["status"])
    op.create_index("ix_meetings_title", "meetings", ["title"])

    op.create_table(
        "transcript_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_transcript_chunks_meeting_id", "transcript_chunks", ["meeting_id"])
    op.create_index(
        "ix_transcript_chunks_embedding_hnsw",
        "transcript_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_chunks_embedding_hnsw", table_name="transcript_chunks")
    op.drop_index("ix_transcript_chunks_meeting_id", table_name="transcript_chunks")
    op.drop_table("transcript_chunks")
    op.drop_index("ix_meetings_title", table_name="meetings")
    op.drop_index("ix_meetings_status", table_name="meetings")
    op.drop_index("ix_meetings_created_at", table_name="meetings")
    op.drop_table("meetings")
    meeting_status.drop(op.get_bind(), checkfirst=True)
