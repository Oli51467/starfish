from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_current_user_profile
from models.schemas import (
    ResearchHistoryDetailResponse,
    ResearchHistoryListResponse,
    UserProfile,
)
from services.research_history_service import (
    ResearchHistoryService,
    get_research_history_service,
)

router = APIRouter(prefix="/api/research-history", tags=["research-history"])


@router.get("", response_model=ResearchHistoryListResponse)
def list_research_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> ResearchHistoryListResponse:
    return history_service.list_history(user=user, page=page, page_size=page_size)


@router.get("/{history_id}", response_model=ResearchHistoryDetailResponse)
def get_research_history_detail(
    history_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> ResearchHistoryDetailResponse:
    payload = history_service.get_history_detail(user=user, history_id=history_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="research_history_not_found")
    return payload
