from __future__ import annotations

from fastapi import APIRouter, Query

from models.schemas import LineageResponse
from services.lineage_service import get_lineage_service

router = APIRouter(prefix="/api/lineage", tags=["lineage"])
lineage_service = get_lineage_service()


@router.get("/{paper_id}", response_model=LineageResponse)
def get_lineage(
    paper_id: str,
    ancestor_depth: int = Query(default=2, ge=1, le=4),
    descendant_depth: int = Query(default=2, ge=1, le=4),
    citation_types: list[str] | None = Query(default=None),
) -> LineageResponse:
    return lineage_service.get_lineage(
        paper_id=paper_id,
        ancestor_depth=ancestor_depth,
        descendant_depth=descendant_depth,
        citation_types=citation_types,
    )
