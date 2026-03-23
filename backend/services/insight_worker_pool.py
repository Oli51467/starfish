from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from services.insight_agent_contracts import AgentTask, AgentTaskResult

TaskRunner = Callable[[AgentTask, str], Awaitable[AgentTaskResult]]


@dataclass(frozen=True)
class WorkerPoolConfig:
    worker_count: int = 4


class InsightWorkerPool:
    """Queue-based worker pool for parallel insight agent task execution."""

    def __init__(self, *, config: WorkerPoolConfig | None = None) -> None:
        safe = config or WorkerPoolConfig()
        self.worker_count = max(1, int(safe.worker_count))

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
        first_error: Exception | None = None

        async def worker_loop(worker_index: int) -> None:
            nonlocal first_error
            worker_id = f"insight-worker-{worker_index}"
            while True:
                index, task = await queue.get()
                try:
                    if task is None:
                        return
                    result = await runner(task, worker_id)
                    ordered_results[index] = result
                except Exception as exc:  # noqa: BLE001
                    if first_error is None:
                        first_error = exc
                finally:
                    queue.task_done()

        workers = [
            asyncio.create_task(worker_loop(index))
            for index in range(1, self.worker_count + 1)
        ]
        await queue.join()
        await asyncio.gather(*workers, return_exceptions=True)

        if first_error is not None:
            raise first_error
        return [item for item in ordered_results if isinstance(item, AgentTaskResult)]
