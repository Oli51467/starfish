from __future__ import annotations

from functools import lru_cache

from core.exceptions import TaskNotFoundError
from core.task_manager import TaskManager, get_task_manager
from models.schemas import TaskDetailResponse


class TaskService:
    """Task query service for async workflow status."""

    def __init__(self, task_manager: TaskManager | None = None) -> None:
        self.task_manager = task_manager or get_task_manager()

    def get_task(self, task_id: str) -> TaskDetailResponse:
        task = self.task_manager.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"task_id not found: {task_id}")
        return task.to_schema()


@lru_cache
def get_task_service() -> TaskService:
    return TaskService()
