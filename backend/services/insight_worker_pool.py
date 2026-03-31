from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from services.insight_agent_contracts import AgentTask, AgentTaskResult

TaskRunner = Callable[[AgentTask, str], Awaitable[AgentTaskResult]]


@dataclass(frozen=True)
class WorkerPoolConfig:
    worker_count: int = 4
    task_timeout_seconds: float = 75.0


class InsightWorkerPool:
    """Queue-based worker pool for parallel insight agent task execution."""

    def __init__(self, *, config: WorkerPoolConfig | None = None) -> None:
        safe = config or WorkerPoolConfig()
        self.worker_count = max(1, int(safe.worker_count))
        self.task_timeout_seconds = max(1.0, min(300.0, float(safe.task_timeout_seconds)))

    async def run(
        self,
        *,
        tasks: list[AgentTask],
        runner: TaskRunner,
    ) -> list[AgentTaskResult]:
        if not tasks:
            return []

        queue: asyncio.Queue[tuple[int, AgentTask | None]] = asyncio.Queue()
        for index, task in enumerate(tasks):
            await queue.put((index, task))
        for _ in range(self.worker_count):
            await queue.put((-1, None))

        ordered_results: list[AgentTaskResult | None] = [None] * len(tasks)
        async def worker_loop(worker_index: int) -> None:
            worker_id = f"insight-worker-{worker_index}"
            while True:
                index, task = await queue.get()
                try:
                    if task is None:
                        return
                    configured_timeout = max(1.0, float(self.task_timeout_seconds))
                    task_timeout = max(
                        configured_timeout,
                        float(getattr(task, "timeout_seconds", 0.0) or 0.0),
                    )
                    try:
                        result = await asyncio.wait_for(
                            runner(task, worker_id),
                            timeout=task_timeout,
                        )
                    except TimeoutError:
                        result = AgentTaskResult(
                            task_id=str(task.task_id or "").strip(),
                            profile_id=str(task.profile_id or "").strip(),
                            role_id=str(task.role_id or "").strip(),
                            status="failed",
                            output="",
                            extra={
                                "error": "worker_task_timeout",
                                "worker_id": worker_id,
                                "timeout_seconds": round(task_timeout, 2),
                            },
                        )
                    except Exception as exc:  # noqa: BLE001
                        result = AgentTaskResult(
                            task_id=str(task.task_id or "").strip(),
                            profile_id=str(task.profile_id or "").strip(),
                            role_id=str(task.role_id or "").strip(),
                            status="failed",
                            output="",
                            extra={
                                "error": str(exc),
                                "worker_id": worker_id,
                            },
                        )
                    ordered_results[index] = result
                finally:
                    queue.task_done()

        workers = [
            asyncio.create_task(worker_loop(index))
            for index in range(1, self.worker_count + 1)
        ]
        await queue.join()
        await asyncio.gather(*workers, return_exceptions=True)

        return [item for item in ordered_results if isinstance(item, AgentTaskResult)]
