from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth import require_api_token
from config import get_settings
from database import ensure_vector_extension, run_migrations_async
from routes import export, files, integrations, meetings, recording, search, ws


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_vector_extension()
    if settings.run_migrations_on_startup:
        await run_migrations_async()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected_api_dependencies = [Depends(require_api_token)]

app.include_router(recording.router, dependencies=protected_api_dependencies)
app.include_router(meetings.router, dependencies=protected_api_dependencies)
app.include_router(search.router, dependencies=protected_api_dependencies)
app.include_router(export.router, dependencies=protected_api_dependencies)
app.include_router(integrations.router)
app.include_router(files.router, dependencies=protected_api_dependencies)
app.include_router(ws.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
