from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from uuid import uuid4

from models.schemas import TaskDetailResponse


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TaskState:
    task_id: str
    status: str = "pending"
    progress: int = 0
    message: str = "Task created"
    result_id: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_schema(self) -> TaskDetailResponse:
        return TaskDetailResponse(
            task_id=self.task_id,
            status=self.status,
            progress=self.progress,
            message=self.message,
            result_id=self.result_id,
            error=self.error,
        )


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}
        self._lock = Lock()

    def create_task(self, message: str = "Task created") -> TaskState:
        task_id = f"task-{uuid4().hex[:12]}"
        task = TaskState(task_id=task_id, message=message)
        with self._lock:
            self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> TaskState | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        result_id: str | None = None,
        error: str | None = None,
    ) -> TaskState | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = max(0, min(100, progress))
            if message is not None:
                task.message = message
            if result_id is not None:
                task.result_id = result_id
            if error is not None:
                task.error = error
            task.updated_at = _utcnow()
            return task


@lru_cache
def get_task_manager() -> TaskManager:
    return TaskManager()
