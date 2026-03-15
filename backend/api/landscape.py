from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user_profile
from models.schemas import (
    LandscapeGenerateRequest,
    LandscapeResponse,
    LandscapeTaskDetailResponse,
    TaskCreateResponse,
    UserProfile,
)
from services.landscape_service import get_landscape_service

router = APIRouter(prefix="/api/landscape", tags=["landscape"])
landscape_service = get_landscape_service()


@router.post("/generate", response_model=TaskCreateResponse)
async def generate_landscape(
    request: LandscapeGenerateRequest,
    user: UserProfile = Depends(get_current_user_profile),
) -> TaskCreateResponse:
    return await landscape_service.create_landscape_task(request, user=user)


@router.get("/task/{task_id}", response_model=LandscapeTaskDetailResponse)
def get_landscape_task(task_id: str) -> LandscapeTaskDetailResponse:
    payload = landscape_service.get_task(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    return payload


@router.get("/result/{task_id}", response_model=LandscapeResponse)
def get_landscape_result(task_id: str) -> LandscapeResponse:
    payload = landscape_service.get_landscape_by_task(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="result_not_ready_or_not_found")
    return payload


@router.get("/{landscape_id}", response_model=LandscapeResponse)
def get_landscape_by_id(landscape_id: str) -> LandscapeResponse:
    payload = landscape_service.get_landscape(landscape_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="landscape_not_found")
    return payload
