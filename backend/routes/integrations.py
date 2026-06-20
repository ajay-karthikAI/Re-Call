from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html import escape
from typing import Optional

from celery import chain
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_api_token
from database import get_session
from models import IntegrationConnection, Meeting, MeetingStatus
from schemas import (
    IntegrationConnectionResponse,
    IntegrationConnectionsResponse,
    IntegrationSyncRequest,
    IntegrationSyncResponse,
    MeetingResponse,
)
from services.provider_transcript_service import (
    IntegrationConfigError,
    IntegrationError,
    SUPPORTED_PROVIDERS,
    authorization_url,
    exchange_code,
    fetch_provider_transcripts,
    get_provider_config,
    is_configured,
    normalized_provider,
    refresh_access_token,
    token_expiration,
)
from services.transcript_import_service import normalize_transcript, parse_transcript, provider_label
from tasks.analyze_task import analyze_meeting_task
from tasks.embedding_task import embed_meeting_task
from tasks.pptx_task import generate_pptx_task


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("/connections", response_model=IntegrationConnectionsResponse, dependencies=[Depends(require_api_token)])
async def list_connections(session: AsyncSession = Depends(get_session)) -> IntegrationConnectionsResponse:
    stored_connections = (
        await session.execute(select(IntegrationConnection).where(IntegrationConnection.provider.in_(SUPPORTED_PROVIDERS)))
    ).scalars()
    by_provider = {connection.provider: connection for connection in stored_connections}

    connections = []
    for provider in SUPPORTED_PROVIDERS:
        config = get_provider_config(provider)
        connection = by_provider.get(provider)
        connections.append(
            IntegrationConnectionResponse(
                provider=provider,
                label=config.label,
                configured=is_configured(provider),
                connected=connection is not None,
                expires_at=connection.expires_at if connection is not None else None,
                detail=_connection_detail(provider, connection),
            )
        )
    return IntegrationConnectionsResponse(connections=connections)


@router.get("/{provider}/authorize")
async def authorize_provider(provider: str) -> RedirectResponse:
    try:
        url = authorization_url(provider)
    except IntegrationConfigError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except IntegrationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(url)


@router.get("/{provider}/callback")
async def provider_callback(
    provider: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    if error:
        return _callback_page("Connection failed", f"The provider returned: {error}")
    if not code:
        return _callback_page("Connection failed", "The provider did not return an authorization code.")

    try:
        normalized = normalized_provider(provider)
        token_data = await asyncio.to_thread(exchange_code, normalized, code)
    except IntegrationError as token_error:
        return _callback_page("Connection failed", str(token_error))

    access_token = token_data.get("access_token")
    if not access_token:
        return _callback_page("Connection failed", "The provider did not return an access token.")

    connection = await _get_connection(session, normalized)
    now = datetime.now(timezone.utc)
    if connection is None:
        connection = IntegrationConnection(provider=normalized, access_token=access_token, created_at=now, updated_at=now)
        session.add(connection)
    else:
        connection.access_token = access_token
        connection.updated_at = now

    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        connection.refresh_token = refresh_token
    connection.expires_at = token_expiration(token_data)
    connection.metadata_json = {
        "scope": token_data.get("scope"),
        "token_type": token_data.get("token_type"),
    }

    await session.commit()
    return _callback_page(
        "Connected",
        f"{provider_label(normalized)} is connected. You can close this tab and sync transcripts in Re: Call.",
    )


@router.post("/{provider}/sync", response_model=IntegrationSyncResponse, dependencies=[Depends(require_api_token)])
async def sync_provider_transcripts(
    provider: str,
    payload: Optional[IntegrationSyncRequest] = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> IntegrationSyncResponse:
    payload = payload or IntegrationSyncRequest()
    normalized = normalized_provider(provider)
    connection = await _usable_connection(session, normalized)

    try:
        provider_transcripts = await asyncio.to_thread(
            fetch_provider_transcripts,
            normalized,
            connection.access_token,
            payload.days,
            payload.limit,
            payload.teams_join_url,
        )
    except IntegrationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    meetings: list[Meeting] = []
    imported_count = 0
    skipped_count = 0
    for provider_transcript in provider_transcripts:
        meeting, created = await _create_meeting(
            session,
            provider_transcript.title,
            provider_transcript.transcript,
            provider_transcript.duration_seconds,
        )
        meetings.append(meeting)
        if created:
            imported_count += 1
            _start_pipeline(meeting.id)
        else:
            skipped_count += 1

    detail = None
    if not provider_transcripts:
        detail = "No finished transcripts were found yet. Make sure platform transcription was enabled and the meeting has ended."
    elif skipped_count and not imported_count:
        detail = "Those transcripts were already in Re: Call."

    return IntegrationSyncResponse(
        provider=normalized,
        imported_count=imported_count,
        skipped_count=skipped_count,
        meetings=meetings,
        detail=detail,
    )


@router.post(
    "/transcript",
    response_model=MeetingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_token)],
)
async def import_transcript(
    provider: str = Form(...),
    title: Optional[str] = Form(default=None),
    transcript_text: Optional[str] = Form(default=None),
    transcript_file: Optional[UploadFile] = File(default=None),
    session: AsyncSession = Depends(get_session),
) -> Meeting:
    source_name = provider_label(provider)
    transcript = normalize_transcript(transcript_text or "")
    duration_seconds = 0

    if transcript_file is not None:
        data = await transcript_file.read()
        if data:
            parsed_transcript, parsed_duration = parse_transcript(
                data,
                filename=transcript_file.filename,
                content_type=transcript_file.content_type,
            )
            transcript = parsed_transcript
            duration_seconds = parsed_duration

    if len(transcript.split()) < 8:
        raise HTTPException(
            status_code=400,
            detail="Import a longer transcript. Re: Call needs at least a few sentences to analyze.",
        )

    meeting_title = (title or "").strip()[:240] or f"{source_name} transcript import"
    meeting, created = await _create_meeting(session, meeting_title, transcript, duration_seconds)
    if created:
        _start_pipeline(meeting.id)
    return meeting


async def _get_connection(session: AsyncSession, provider: str) -> Optional[IntegrationConnection]:
    return await session.scalar(select(IntegrationConnection).where(IntegrationConnection.provider == provider))


async def _usable_connection(session: AsyncSession, provider: str) -> IntegrationConnection:
    if not is_configured(provider):
        label = get_provider_config(provider).label
        raise HTTPException(status_code=400, detail=f"{label} OAuth credentials are not configured in the backend .env.")

    connection = await _get_connection(session, provider)
    if connection is None:
        raise HTTPException(status_code=401, detail=f"Connect {provider_label(provider)} before syncing transcripts.")

    expires_at = _aware_datetime(connection.expires_at)
    if expires_at and expires_at <= datetime.now(timezone.utc):
        if not connection.refresh_token:
            raise HTTPException(status_code=401, detail=f"Reconnect {provider_label(provider)} before syncing transcripts.")
        try:
            token_data = await asyncio.to_thread(refresh_access_token, provider, connection.refresh_token)
        except IntegrationError as error:
            raise HTTPException(status_code=401, detail=f"Could not refresh {provider_label(provider)}: {error}") from error

        connection.access_token = token_data.get("access_token") or connection.access_token
        connection.refresh_token = token_data.get("refresh_token") or connection.refresh_token
        connection.expires_at = token_expiration(token_data)
        connection.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(connection)

    return connection


async def _create_meeting(
    session: AsyncSession,
    title: str,
    transcript: str,
    duration_seconds: int,
) -> tuple[Meeting, bool]:
    existing = await session.scalar(
        select(Meeting).where(Meeting.title == title[:240], Meeting.transcript == transcript).limit(1)
    )
    if existing is not None:
        return existing, False

    meeting = Meeting(
        title=title[:240],
        transcript=transcript,
        duration_seconds=duration_seconds,
        status=MeetingStatus.analyzing,
    )
    session.add(meeting)
    await session.commit()
    await session.refresh(meeting)
    return meeting, True


def _start_pipeline(meeting_id) -> None:
    pipeline = chain(
        analyze_meeting_task.s(str(meeting_id)),
        embed_meeting_task.s(),
        generate_pptx_task.s(),
    )
    pipeline.delay()


def _connection_detail(provider: str, connection: Optional[IntegrationConnection]) -> Optional[str]:
    if not is_configured(provider):
        return "Add OAuth client ID and secret in the backend .env."
    if connection is None:
        return "Ready to connect."
    expires_at = _aware_datetime(connection.expires_at)
    if expires_at and expires_at <= datetime.now(timezone.utc):
        return "Token expired; reconnect or sync to refresh."
    return "Connected."


def _aware_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _callback_page(title: str, message: str) -> HTMLResponse:
    safe_title = escape(title)
    safe_message = escape(message)
    return HTMLResponse(
        f"""
        <!doctype html>
        <html>
          <head>
            <meta charset="utf-8">
            <title>Re: Call - {safe_title}</title>
            <style>
              body {{
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #08090a;
                color: #f7f8f6;
                font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              }}
              main {{
                width: min(520px, calc(100vw - 40px));
                border: 1px solid rgba(168, 255, 96, 0.28);
                border-radius: 10px;
                background: #111315;
                padding: 28px;
                box-shadow: 0 30px 90px rgba(0, 0, 0, 0.45);
              }}
              h1 {{ margin: 0 0 10px; font-size: 26px; }}
              p {{ margin: 0; color: #a3aaa0; line-height: 1.5; }}
              strong {{ color: #a8ff60; }}
            </style>
          </head>
          <body>
            <main>
              <h1><strong>Re: Call</strong> {safe_title}</h1>
              <p>{safe_message}</p>
            </main>
          </body>
        </html>
        """
    )
