from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_current_user_profile
from models.schemas import (
    PaperSignal,
    PaperSignalEventListResponse,
    PaperSignalEventReadResponse,
    PaperSignalRefreshRequest,
    PaperSignalRefreshResponse,
    UserProfile,
)
from services.paper_signal_service import PaperSignalService, get_paper_signal_service

router = APIRouter(prefix="/api/paper-signals", tags=["paper-signals"])


@router.post("/refresh", response_model=PaperSignalRefreshResponse)
async def refresh_saved_paper_signals(
    request: PaperSignalRefreshRequest,
    user: UserProfile = Depends(get_current_user_profile),
    signal_service: PaperSignalService = Depends(get_paper_signal_service),
) -> PaperSignalRefreshResponse:
    try:
        return await signal_service.refresh_saved_paper_signals(
            user=user,
            collection_id=request.collection_id,
            limit=request.limit,
            force_refresh=request.force_refresh,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"paper_signal_refresh_failed: {exc}") from exc


@router.get("/events", response_model=PaperSignalEventListResponse)
def list_saved_paper_signal_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    unread_only: bool = Query(default=False),
    paper_id: str = Query(default="", max_length=200),
    saved_paper_id: str = Query(default="", max_length=200),
    user: UserProfile = Depends(get_current_user_profile),
    signal_service: PaperSignalService = Depends(get_paper_signal_service),
) -> PaperSignalEventListResponse:
    return signal_service.list_signal_events(
        user=user,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
        paper_id=paper_id,
        saved_paper_id=saved_paper_id,
    )


@router.patch("/events/{event_id}/read", response_model=PaperSignalEventReadResponse)
def mark_saved_paper_signal_event_read(
    event_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    signal_service: PaperSignalService = Depends(get_paper_signal_service),
) -> PaperSignalEventReadResponse:
    updated = signal_service.mark_event_read(user=user, event_id=event_id)
    if not updated:
        raise HTTPException(status_code=404, detail="paper_signal_event_not_found")
    return PaperSignalEventReadResponse(updated=True)


@router.get("/{paper_id:path}", response_model=PaperSignal)
async def get_paper_signal(
    paper_id: str,
    force_refresh: bool = Query(default=False),
    _: UserProfile = Depends(get_current_user_profile),
    signal_service: PaperSignalService = Depends(get_paper_signal_service),
) -> PaperSignal:
    try:
        return await signal_service.get_paper_signal(
            paper_id=paper_id,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        if str(exc).startswith("paper_not_found"):
            raise HTTPException(status_code=404, detail="paper_not_found") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"paper_signal_failed: {exc}") from exc
