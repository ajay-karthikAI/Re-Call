from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from schemas import SearchRequest, SearchResponse
from services.rag_service import search as rag_search


router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(payload: SearchRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return await rag_search(session, payload.query, payload.limit)
