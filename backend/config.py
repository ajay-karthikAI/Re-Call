from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    app_name: str = Field(default="Re: Call", alias="APP_NAME")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
    backend_public_url: str = Field(default="http://127.0.0.1:8000", alias="BACKEND_PUBLIC_URL")
    frontend_origin: str = Field(default="http://127.0.0.1:5173", alias="FRONTEND_ORIGIN")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-5", alias="OPENAI_CHAT_MODEL")
    openai_transcription_model: str = Field(default="whisper-1", alias="OPENAI_TRANSCRIPTION_MODEL")
    openai_embedding_model: str = Field(default="text-embedding-3-large", alias="OPENAI_EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS")

    database_url: str = Field(
        default="postgresql+asyncpg://recall:recall@localhost:5433/recall",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: Optional[str] = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend: Optional[str] = Field(default=None, alias="CELERY_RESULT_BACKEND")

    aws_access_key_id: str = Field(default="", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", alias="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    s3_bucket_name: str = Field(default="", alias="S3_BUCKET_NAME")
    local_storage_dir: Path = Field(default=BASE_DIR / "storage", alias="LOCAL_STORAGE_DIR")

    zoom_client_id: str = Field(default="", alias="ZOOM_CLIENT_ID")
    zoom_client_secret: str = Field(default="", alias="ZOOM_CLIENT_SECRET")
    zoom_oauth_scopes: str = Field(
        default=(
            "cloud_recording:read:list_recording_files "
            "cloud_recording:read:meeting_recording "
            "cloud_recording:read:meeting_transcript"
        ),
        alias="ZOOM_OAUTH_SCOPES",
    )

    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_oauth_scopes: str = Field(
        default="openid email profile https://www.googleapis.com/auth/meetings.space.readonly",
        alias="GOOGLE_OAUTH_SCOPES",
    )

    microsoft_client_id: str = Field(default="", alias="MICROSOFT_CLIENT_ID")
    microsoft_client_secret: str = Field(default="", alias="MICROSOFT_CLIENT_SECRET")
    microsoft_tenant_id: str = Field(default="common", alias="MICROSOFT_TENANT_ID")
    microsoft_oauth_scopes: str = Field(
        default="offline_access User.Read OnlineMeetings.Read OnlineMeetingTranscript.Read.All",
        alias="MICROSOFT_OAUTH_SCOPES",
    )

    run_migrations_on_startup: bool = Field(default=True, alias="RUN_MIGRATIONS_ON_STARTUP")

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
