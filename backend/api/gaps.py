from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from models.schemas import GapsResponse
from services.gap_service import get_gap_service

router = APIRouter(prefix="/api/gaps", tags=["gaps"])
gap_service = get_gap_service()


@router.get("/{map_id}", response_model=GapsResponse)
def get_gaps(
    map_id: str,
    gap_types: list[str] | None = Query(default=None),
    min_score: int = Query(default=60, ge=0, le=100),
) -> GapsResponse:
    try:
        return gap_service.get_gaps(map_id=map_id, gap_types=gap_types, min_score=min_score)
    except KeyError:
        raise HTTPException(status_code=404, detail="map_not_found") from None
