from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.exceptions import MapNotFoundError
from models.schemas import ReadingListResponse
from services.reading_list_service import get_reading_list_service

router = APIRouter(prefix="/api/reading-list", tags=["reading-list"])
reading_list_service = get_reading_list_service()


@router.get("/{map_id}", response_model=ReadingListResponse)
def get_reading_list(
    map_id: str,
    focus_area: str | None = Query(default=None),
    max_papers: int = Query(default=20, ge=5, le=30),
) -> ReadingListResponse:
    try:
        return reading_list_service.get_reading_list(
            map_id=map_id,
            focus_area=focus_area,
            max_papers=max_papers,
        )
    except MapNotFoundError:
        raise HTTPException(status_code=404, detail="map_not_found") from None
