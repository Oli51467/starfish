from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models.schemas import TaskDetailResponse
from services.map_service import get_map_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
map_service = get_map_service()


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task(task_id: str) -> TaskDetailResponse:
    task = map_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task
