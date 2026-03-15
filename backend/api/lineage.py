from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from models.schemas import LineageResponse
from services.lineage_service import get_lineage_service

router = APIRouter(prefix="/api/lineage", tags=["lineage"])
lineage_service = get_lineage_service()


@router.get("/{paper_id:path}", response_model=LineageResponse)
async def get_lineage(
    paper_id: str,
    ancestor_depth: int = Query(default=2, ge=1, le=4),
    descendant_depth: int = Query(default=2, ge=1, le=4),
    citation_types: list[str] | None = Query(default=None),
    force_refresh: bool = Query(default=False),
) -> LineageResponse:
    try:
        return await lineage_service.get_lineage(
            paper_id=paper_id,
            ancestor_depth=ancestor_depth,
            descendant_depth=descendant_depth,
            citation_types=citation_types,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"lineage_build_failed: {exc}") from exc
