from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent
APP_ENV_VALUES = {"development", "production"}
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
DEVELOPMENT_CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]


def _clean(value: Optional[str]) -> str:
    return str(value or "").strip()


def _url_hostname(value: str) -> Optional[str]:
    try:
        return urlparse(value).hostname
    except ValueError:
        return None


def _validate_required_url(name: str, value: str, errors: list[str]) -> None:
    cleaned = _clean(value)
    hostname = _url_hostname(cleaned)
    if not cleaned:
        errors.append(f"{name} is required when APP_ENV=production")
    elif not hostname:
        errors.append(f"{name} must be a valid URL when APP_ENV=production")
    elif hostname.lower() in LOCAL_HOSTNAMES:
        errors.append(f"{name} must not point to localhost when APP_ENV=production")


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="Re: Call", alias="APP_NAME")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
    backend_public_url: str = Field(default="http://127.0.0.1:8000", alias="BACKEND_PUBLIC_URL")
    frontend_origin: str = Field(default="http://127.0.0.1:5173", alias="FRONTEND_ORIGIN")
    recall_api_token: str = Field(default="", alias="RECALL_API_TOKEN")

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

    @field_validator("app_env")
    @classmethod
    def normalize_app_env(cls, value: str) -> str:
        normalized = _clean(value).lower() or "development"
        if normalized not in APP_ENV_VALUES:
            allowed = ", ".join(sorted(APP_ENV_VALUES))
            raise ValueError(f"APP_ENV must be one of: {allowed}")
        return normalized

    @field_validator(
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_region",
        "s3_bucket_name",
        mode="before",
    )
    @classmethod
    def normalize_storage_strings(cls, value: Optional[str]) -> str:
        return _clean(value)

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        errors: list[str] = []

        if self.uses_s3_storage:
            if not _clean(self.aws_region):
                errors.append("AWS_REGION is required when S3_BUCKET_NAME is set")
            if bool(_clean(self.aws_access_key_id)) != bool(_clean(self.aws_secret_access_key)):
                errors.append(
                    "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set together, "
                    "or both left blank to use an AWS instance/task role"
                )

        if not self.is_production:
            if errors:
                details = "\n - ".join(errors)
                raise ValueError(f"Invalid storage configuration:\n - {details}")
            return self

        _validate_required_url("BACKEND_PUBLIC_URL", self.backend_public_url, errors)
        _validate_required_url("FRONTEND_ORIGIN", self.frontend_origin, errors)
        _validate_required_url("DATABASE_URL", self.database_url, errors)
        _validate_required_url("REDIS_URL", self.redis_url, errors)

        if _clean(self.celery_broker_url):
            _validate_required_url("CELERY_BROKER_URL", self.celery_broker_url or "", errors)
        if _clean(self.celery_result_backend):
            _validate_required_url("CELERY_RESULT_BACKEND", self.celery_result_backend or "", errors)
        if not _clean(self.openai_api_key):
            errors.append("OPENAI_API_KEY is required when APP_ENV=production")
        if not self.uses_s3_storage:
            errors.append("S3_BUCKET_NAME is required when APP_ENV=production so storage uses S3 instead of local disk")
        if not _clean(self.recall_api_token):
            errors.append("RECALL_API_TOKEN is required when APP_ENV=production")
        elif len(_clean(self.recall_api_token)) < 24:
            errors.append("RECALL_API_TOKEN must be at least 24 characters when APP_ENV=production")

        if errors:
            details = "\n - ".join(errors)
            raise ValueError(f"Invalid production configuration:\n - {details}")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def uses_s3_storage(self) -> bool:
        return bool(_clean(self.s3_bucket_name))

    @property
    def allowed_cors_origins(self) -> list[str]:
        origins = [self.frontend_origin]
        if not self.is_production:
            origins.extend(DEVELOPMENT_CORS_ORIGINS)
        return list(dict.fromkeys(origin.rstrip("/") for origin in origins if _clean(origin)))

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
