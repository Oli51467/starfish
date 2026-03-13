from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.exceptions import TaskNotFoundError
from models.schemas import TaskDetailResponse
from services.task_service import get_task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
task_service = get_task_service()


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task(task_id: str) -> TaskDetailResponse:
    try:
        return task_service.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task_not_found") from None
