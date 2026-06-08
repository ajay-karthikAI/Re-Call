from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services.s3_service import get_local_file_path


router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{storage_key:path}")
async def download_local_file(storage_key: str) -> FileResponse:
    file_path = get_local_file_path(storage_key)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=file_path.name)
