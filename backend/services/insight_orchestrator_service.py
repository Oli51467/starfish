from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Awaitable, Callable

from core.settings import get_settings
from services.insight_agent_contracts import (
    AgentProfile,
    AgentTask,
    AgentTaskResult,
    InsightOrchestrationJournal,
    RoundExecutionResult,
    SubAgentRequest,
    build_task_id,
)
from services.insight_worker_pool import InsightWorkerPool, WorkerPoolConfig

TaskExecutor = Callable[[AgentTask, str], Awaitable[AgentTaskResult]]
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class OrchestratorLimits:
    max_subagent_depth: int = 2
    max_subtasks_per_round: int = 24
    max_subtasks_per_parent: int = 2
    max_batch_size: int = 12


class InsightOrchestratorService:
    """Coordinator for insight multi-agent task planning and execution."""

    def __init__(
        self,
        *,
        limits: OrchestratorLimits | None = None,
        worker_pool: InsightWorkerPool | None = None,
    ) -> None:
        self.limits = limits or OrchestratorLimits()
        self.worker_pool = worker_pool or InsightWorkerPool()

    def plan_round_tasks(
        self,
        *,
        run_id: str,
        round_index: int,
        profiles: list[AgentProfile],
        query: str,
        language: str,
        input_type: str,
        objective: str,
        shared_context: dict[str, Any] | None = None,
    ) -> list[AgentTask]:
        tasks: list[AgentTask] = []
        context = dict(shared_context or {})
        for profile in profiles:
            tasks.append(
                AgentTask(
                    run_id=run_id,
                    task_id=build_task_id("insight-agent"),
                    profile_id=profile.profile_id,
                    role_id=profile.role_id,
                    round_index=round_index,
                    depth=0,
                    query=query,
                    language=language,
                    input_type=input_type,
                    objective=objective,
                    context=dict(context),
                )
            )
        return tasks

    async def execute_round(
        self,
        *,
        round_index: int,
        base_tasks: list[AgentTask],
        profiles_by_id: dict[str, AgentProfile],
        executor: TaskExecutor,
        event_callback: EventCallback | None = None,
    ) -> RoundExecutionResult:
        """Execute one round using orchestrated scheduling (phase-2 baseline)."""
        all_results: list[AgentTaskResult] = []
        pending: list[AgentTask] = list(base_tasks)
        spawned_count = 0
        processed_count = 0

        while pending:
            safe_batch_size = max(1, int(self.limits.max_batch_size or 1))
            batch = list(pending[:safe_batch_size])
            pending = list(pending[safe_batch_size:])
            batch_results = await self._execute_batch(
                tasks=batch,
                executor=executor,
                event_callback=event_callback,
            )
            all_results.extend(batch_results)
            processed_count += len(batch_results)

            for result in batch_results:
                parent_task = next((item for item in batch if item.task_id == result.task_id), None)
                if parent_task is None:
                    continue
                remaining_spawn_budget = max(0, self.limits.max_subtasks_per_round - spawned_count)
                next_tasks = self._build_subagent_tasks(
                    parent_task=parent_task,
                    result=result,
                    profiles_by_id=profiles_by_id,
                    remaining=remaining_spawn_budget,
                )
                if not next_tasks:
                    continue
                spawned_count += len(next_tasks)
                pending.extend(next_tasks)

            if processed_count >= self.limits.max_subtasks_per_round + len(base_tasks):
                break

        return RoundExecutionResult(
            round_index=round_index,
            results=all_results,
            spawned_task_count=spawned_count,
            total_task_count=processed_count,
        )

    async def _execute_batch(
        self,
        *,
        tasks: list[AgentTask],
        executor: TaskExecutor,
        event_callback: EventCallback | None = None,
    ) -> list[AgentTaskResult]:
        results: list[AgentTaskResult] = []
        if not tasks:
            return results

        async def run_one(task: AgentTask, worker_id: str) -> AgentTaskResult:
            if event_callback is not None:
                await event_callback(
                    {
                        "type": "insight_orchestrator_task_started",
                        "task_id": task.task_id,
                        "profile_id": task.profile_id,
                        "role_id": task.role_id,
                        "round_index": task.round_index,
                        "depth": task.depth,
                        "worker_id": worker_id,
                    }
                )
            result = await executor(task, worker_id)
            if event_callback is not None:
                await event_callback(
                    {
                        "type": "insight_orchestrator_task_finished",
                        "task_id": task.task_id,
                        "profile_id": task.profile_id,
                        "role_id": task.role_id,
                        "status": result.status,
                        "worker_id": worker_id,
                    }
                )
            return result

        gathered = await self.worker_pool.run(
            tasks=tasks,
            runner=run_one,
        )
        results.extend(gathered)
        return results

    def _build_subagent_tasks(
        self,
        *,
        parent_task: AgentTask,
        result: AgentTaskResult,
        profiles_by_id: dict[str, AgentProfile],
        remaining: int,
    ) -> list[AgentTask]:
        if remaining <= 0:
            return []
        if parent_task.depth >= self.limits.max_subagent_depth:
            return []
        requests = list(result.subagent_requests or [])
        if not requests:
            return []

        parent_profile = profiles_by_id.get(parent_task.profile_id)
        max_per_parent = max(1, int(self.limits.max_subtasks_per_parent))
        if parent_profile is not None:
            max_per_parent = max(0, min(max_per_parent, int(parent_profile.max_subagents)))
        if max_per_parent <= 0:
            return []

        safe_requests: list[SubAgentRequest] = []
        for item in requests:
            if not isinstance(item, SubAgentRequest):
                continue
            safe_requests.append(item)
            if len(safe_requests) >= max_per_parent:
                break
        if not safe_requests:
            return []

        output: list[AgentTask] = []
        for request in safe_requests[:remaining]:
            target_profile_id = str(request.profile_id or "").strip() or parent_task.profile_id
            target_profile = profiles_by_id.get(target_profile_id)
            if target_profile is None:
                continue
            output.append(
                AgentTask(
                    run_id=parent_task.run_id,
                    task_id=build_task_id("insight-subagent"),
                    profile_id=target_profile.profile_id,
                    role_id=target_profile.role_id,
                    round_index=parent_task.round_index,
                    depth=parent_task.depth + 1,
                    parent_task_id=parent_task.task_id,
                    query=parent_task.query,
                    language=parent_task.language,
                    input_type=parent_task.input_type,
                    objective=str(request.objective or "").strip() or parent_task.objective,
                    context={
                        **dict(parent_task.context or {}),
                        **dict(request.context_patch or {}),
                    },
                    budget_cost=parent_task.budget_cost,
                    timeout_seconds=parent_task.timeout_seconds,
                )
            )
        return output

    async def execute(
        self,
        *,
        run_id: str,
        rounds: int,
        profiles: list[AgentProfile],
        query: str,
        language: str,
        input_type: str,
        objective: str,
        base_context_builder: Callable[[int], dict[str, Any]],
        executor: TaskExecutor,
        event_callback: EventCallback | None = None,
    ) -> InsightOrchestrationJournal:
        journal = InsightOrchestrationJournal(run_id=run_id)
        profiles_by_id = {item.profile_id: item for item in profiles}
        total_rounds = max(1, int(rounds or 1))

        for round_index in range(1, total_rounds + 1):
            base_context = dict(base_context_builder(round_index) or {})
            base_tasks = self.plan_round_tasks(
                run_id=run_id,
                round_index=round_index,
                profiles=profiles,
                query=query,
                language=language,
                input_type=input_type,
                objective=objective,
                shared_context=base_context,
            )
            journal.append_event(
                "round_started",
                round_index=round_index,
                planned_tasks=len(base_tasks),
            )
            round_result = await self.execute_round(
                round_index=round_index,
                base_tasks=base_tasks,
                profiles_by_id=profiles_by_id,
                executor=executor,
                event_callback=event_callback,
            )
            journal.rounds.append(round_result)
            journal.append_event(
                "round_completed",
                round_index=round_index,
                completed_tasks=round_result.total_task_count,
                spawned_tasks=round_result.spawned_task_count,
            )
        return journal


@lru_cache
def get_insight_orchestrator_service() -> InsightOrchestratorService:
    settings = get_settings()
    return InsightOrchestratorService(
        limits=OrchestratorLimits(
            max_subagent_depth=max(0, int(settings.insight_max_subagent_depth)),
            max_subtasks_per_round=max(1, int(settings.insight_max_subtasks_per_round)),
            max_subtasks_per_parent=max(1, int(settings.insight_max_subtasks_per_parent)),
            max_batch_size=max(1, min(64, int(settings.insight_worker_count) * 2)),
        ),
        worker_pool=InsightWorkerPool(
            config=WorkerPoolConfig(
                worker_count=max(1, int(settings.insight_worker_count)),
                task_timeout_seconds=max(10.0, float(settings.insight_worker_task_timeout_seconds)),
            )
        ),
    )
