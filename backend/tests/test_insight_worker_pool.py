from __future__ import annotations

import asyncio
import unittest

from services.insight_agent_contracts import AgentTask, AgentTaskResult
from services.insight_worker_pool import InsightWorkerPool, WorkerPoolConfig


def _build_task(*, task_id: str, timeout_seconds: float = 25.0) -> AgentTask:
    return AgentTask(
        run_id="run-1",
        task_id=task_id,
        profile_id="profile-1",
        role_id="role-1",
        round_index=1,
        depth=0,
        query="q",
        language="zh",
        input_type="domain",
        objective="obj",
        timeout_seconds=timeout_seconds,
    )


class InsightWorkerPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_marks_timeout_task_as_failed(self) -> None:
        pool = InsightWorkerPool(
            config=WorkerPoolConfig(worker_count=1, task_timeout_seconds=0.05),
        )
        tasks = [_build_task(task_id="t-timeout", timeout_seconds=0.1)]

        async def runner(task: AgentTask, worker_id: str) -> AgentTaskResult:
            _ = task, worker_id
            await asyncio.sleep(1.2)
            return AgentTaskResult(
                task_id="t-timeout",
                profile_id="profile-1",
                role_id="role-1",
                status="completed",
                output="ok",
            )

        results = await pool.run(tasks=tasks, runner=runner)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "failed")
        self.assertEqual(str(results[0].extra.get("error") or ""), "worker_task_timeout")

    async def test_run_marks_exception_task_as_failed(self) -> None:
        pool = InsightWorkerPool(config=WorkerPoolConfig(worker_count=1))
        tasks = [_build_task(task_id="t-error")]

        async def runner(task: AgentTask, worker_id: str) -> AgentTaskResult:
            _ = task, worker_id
            raise RuntimeError("boom")

        results = await pool.run(tasks=tasks, runner=runner)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "failed")
        self.assertIn("boom", str(results[0].extra.get("error") or ""))

    async def test_run_preserves_successful_results(self) -> None:
        pool = InsightWorkerPool(config=WorkerPoolConfig(worker_count=2))
        tasks = [_build_task(task_id="t1"), _build_task(task_id="t2")]

        async def runner(task: AgentTask, worker_id: str) -> AgentTaskResult:
            _ = worker_id
            await asyncio.sleep(0.01)
            return AgentTaskResult(
                task_id=task.task_id,
                profile_id=task.profile_id,
                role_id=task.role_id,
                status="completed",
                output=f"done:{task.task_id}",
            )

        results = await pool.run(tasks=tasks, runner=runner)
        self.assertEqual([item.task_id for item in results], ["t1", "t2"])
        self.assertTrue(all(item.status == "completed" for item in results))


if __name__ == "__main__":
    unittest.main()
