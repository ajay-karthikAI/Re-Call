from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Meeting
from schemas import ExportResponse
from services.export_service import ensure_export, normalize_export_format


router = APIRouter(prefix="/api/export", tags=["export"])


@router.post("/{meeting_id}", response_model=ExportResponse)
async def export_meeting(
    meeting_id: UUID,
    export_format: str = Query("pptx", alias="format"),
    session: AsyncSession = Depends(get_session),
) -> ExportResponse:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    try:
        normalized_format = normalize_export_format(export_format)
        download_url, filename = await ensure_export(session, meeting_id, normalized_format)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return ExportResponse(
        meeting_id=meeting_id,
        download_url=download_url,
        pptx_url=download_url if normalized_format == "pptx" else None,
        filename=filename,
        format=normalized_format,
        status="ready",
    )


@router.get("/{meeting_id}/download", response_model=ExportResponse)
async def download_export(
    meeting_id: UUID,
    export_format: str = Query("pptx", alias="format"),
    session: AsyncSession = Depends(get_session),
) -> ExportResponse:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    try:
        normalized_format = normalize_export_format(export_format)
        download_url, filename = await ensure_export(session, meeting_id, normalized_format)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return ExportResponse(
        meeting_id=meeting_id,
        download_url=download_url,
        pptx_url=download_url if normalized_format == "pptx" else None,
        filename=filename,
        format=normalized_format,
        status="ready",
    )
