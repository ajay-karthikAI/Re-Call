from celery import Celery

from config import get_settings


settings = get_settings()

celery_app = Celery(
    "recall",
    broker=settings.broker_url,
    backend=settings.result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "tasks.transcribe_task.*": {"queue": "transcription"},
        "tasks.analyze_task.*": {"queue": "analysis"},
        "tasks.embedding_task.*": {"queue": "analysis"},
        "tasks.pptx_task.*": {"queue": "analysis"},
    },
    imports=(
        "tasks.transcribe_task",
        "tasks.analyze_task",
        "tasks.embedding_task",
        "tasks.pptx_task",
        "tasks.task_utils",
    ),
)
