from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from time import perf_counter
from typing import Any, AsyncGenerator, Awaitable, Callable
from uuid import uuid4

from models.schemas import UserProfile
from agents.pipeline.state import PipelineState, build_initial_state

_FINAL_STATUSES = {"completed", "failed", "stopped"}

_DEFAULT_MAX_NEGOTIATION_ROUNDS = 16
_DEFAULT_MAX_REBID_PER_TASK = 2
_COORDINATOR_NODE = "coordinator"

_TASK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "planner": ("router",),
    "router": ("search",),
    "search": ("checkpoint_1",),
    "checkpoint_1": ("graph_build",),
    "graph_build": ("checkpoint_2",),
    "checkpoint_2": ("insight",),
    "insight": (),
}

_TASK_PRIORITY: dict[str, int] = {
    "planner": 10,
    "router": 9,
    "search": 8,
    "checkpoint_1": 7,
    "graph_build": 6,
    "checkpoint_2": 5,
    "insight": 4,
}

_TASK_ESTIMATED_LATENCY_MS: dict[str, int] = {
    "planner": 1800,
    "router": 200,
    "search": 4800,
    "graph_build": 5200,
    "checkpoint_1": 600,
    "checkpoint_2": 900,
    "insight": 14000,
}

_TASK_ESTIMATED_COST: dict[str, float] = {
    "planner": 0.8,
    "router": 0.1,
    "search": 1.2,
    "graph_build": 1.4,
    "checkpoint_1": 0.2,
    "checkpoint_2": 0.2,
    "insight": 2.2,
}

_TASK_BASE_CONFIDENCE: dict[str, float] = {
    "planner": 0.88,
    "router": 0.98,
    "search": 0.82,
    "graph_build": 0.80,
    "checkpoint_1": 0.96,
    "checkpoint_2": 0.96,
    "insight": 0.78,
}

NodeCallable = Callable[[PipelineState], Awaitable[PipelineState]]


class PipelineRuntimeError(RuntimeError):
    """Raised when runtime session operation is invalid."""


class PipelineStoppedError(RuntimeError):
    """Raised inside graph nodes when user requests stop."""


@dataclass(frozen=True)
class _TaskIntent:
    task_id: str
    kind: str
    priority: int
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _AgentRegistration:
    agent_id: str
    task_kinds: tuple[str, ...]
    node_fn: NodeCallable
    profile: str = "balanced"
    confidence_bias: float = 0.0
    cost_multiplier: float = 1.0
    latency_multiplier: float = 1.0
    critic_strictness: float = 1.0


@dataclass(frozen=True)
class _AgentBid:
    bid_id: str
    task_id: str
    task_kind: str
    agent_id: str
    confidence: float
    estimated_latency_ms: int
    estimated_cost: float
    profile: str
    rationale: str
    submitted_at: datetime


@dataclass(frozen=True)
class _TaskContract:
    contract_id: str
    task_id: str
    task_kind: str
    agent_id: str
    confidence: float
    estimated_latency_ms: int
    estimated_cost: float
    profile: str
    round_index: int
    awarded_at: datetime


@dataclass
class _AgentPerformance:
    awards: int = 0
    executions: int = 0
    successes: int = 0
    vetoes: int = 0
    failures: int = 0
    total_latency_ms: int = 0


@dataclass(frozen=True)
class _CriticVerdict:
    approved: bool
    reason: str
    severity: str = "info"


@dataclass
class _PipelineSessionRuntime:
    session_id: str
    user_id: str
    state: PipelineState
    status: str = "pending"
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events: list[dict[str, Any]] = field(default_factory=list)
    event_condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[Any] | None = None
    waiting_checkpoint: str | None = None
    resume_event: asyncio.Event | None = None
    resume_feedback: str = ""
    stop_requested: bool = False
    agenda: list[_TaskIntent] = field(default_factory=list)
    contracts: list[_TaskContract] = field(default_factory=list)
    negotiation_round: int = 0
    max_negotiation_rounds: int = _DEFAULT_MAX_NEGOTIATION_ROUNDS
    max_rebid_per_task: int = _DEFAULT_MAX_REBID_PER_TASK
    budget_limit: float = 10.0
    budget_spent: float = 0.0
    task_retry_count: dict[str, int] = field(default_factory=dict)
    agent_performance: dict[str, _AgentPerformance] = field(default_factory=dict)


class PipelineRuntimeService:
    def __init__(self) -> None:
        self._sessions: dict[str, _PipelineSessionRuntime] = {}
        self._sessions_lock = asyncio.Lock()

    async def start_session(
        self,
        *,
        user: UserProfile,
        input_type: str,
        input_value: str,
        paper_range_years: int | None,
        quick_mode: bool,
    ) -> str:
        session_id = str(uuid4())
        state = build_initial_state(
            session_id=session_id,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
            input_type=input_type,
            input_value=input_value,
            quick_mode=quick_mode,
            paper_range_years=paper_range_years,
        )
        runtime = _PipelineSessionRuntime(
            session_id=session_id,
            user_id=user.id,
            state=state,
            status="pending",
            max_rebid_per_task=1 if quick_mode else _DEFAULT_MAX_REBID_PER_TASK,
            budget_limit=self._resolve_session_budget(
                input_type=str(input_type or "").strip().lower(),
                quick_mode=quick_mode,
            ),
        )

        async with self._sessions_lock:
            active_runtime = self._find_active_runtime_for_user_locked(user.id)
            if active_runtime is not None:
                raise PipelineRuntimeError(f"active_session_exists:{active_runtime.session_id}")
            self._sessions[session_id] = runtime

        runtime.task = asyncio.create_task(self._run_session(session_id))
        return session_id

    async def _run_session(self, session_id: str) -> None:
        runtime = await self._require_runtime(session_id)
        runtime.status = "running"
        runtime.updated_at = datetime.now(timezone.utc)
        runtime.budget_limit = max(
            float(runtime.budget_limit),
            self._resolve_session_budget(
                input_type=str(runtime.state.get("input_type") or "").strip().lower(),
                quick_mode=bool(runtime.state.get("quick_mode")),
            ),
        )

        try:
            runtime.agenda = [self._build_task_intent(kind="planner", metadata={"source": "bootstrap"})]
            registry = self._resolve_agent_registry()

            while runtime.agenda:
                await self.ensure_active(session_id)
                runtime.negotiation_round += 1
                if runtime.negotiation_round > runtime.max_negotiation_rounds:
                    raise RuntimeError("negotiation_round_limit_exceeded")

                runtime.agenda.sort(
                    key=lambda item: (
                        -int(item.priority),
                        item.created_at,
                    )
                )
                intent = runtime.agenda.pop(0)
                await self._publish_event(
                    runtime,
                    {
                        "type": "negotiation_round_started",
                        "node": _COORDINATOR_NODE,
                        "round": runtime.negotiation_round,
                        "task_id": intent.task_id,
                        "task_kind": intent.kind,
                        "agenda_size": len(runtime.agenda),
                    },
                )
                bids = self._collect_bids(
                    runtime=runtime,
                    intent=intent,
                    registry=registry,
                )
                for bid in bids:
                    await self._publish_event(
                        runtime,
                        {
                            "type": "negotiation_bid_received",
                            "node": _COORDINATOR_NODE,
                            "round": runtime.negotiation_round,
                            "task_id": intent.task_id,
                            "task_kind": intent.kind,
                            "agent_id": bid.agent_id,
                            "profile": bid.profile,
                            "confidence": bid.confidence,
                            "estimated_latency_ms": bid.estimated_latency_ms,
                            "estimated_cost": bid.estimated_cost,
                            "rationale": bid.rationale,
                        },
                    )

                winning_bid = self._select_winning_bid(
                    runtime=runtime,
                    intent=intent,
                    bids=bids,
                )
                if winning_bid is None:
                    if bids:
                        raise RuntimeError(f"negotiation_budget_exhausted:{intent.kind}")
                    raise RuntimeError(f"no_agent_bid_for_task:{intent.kind}")

                contract = self._award_contract(
                    runtime=runtime,
                    intent=intent,
                    bid=winning_bid,
                )
                runtime.contracts.append(contract)
                performance = runtime.agent_performance.setdefault(contract.agent_id, _AgentPerformance())
                performance.awards += 1
                await self._publish_event(
                    runtime,
                    {
                        "type": "negotiation_contract_awarded",
                        "node": _COORDINATOR_NODE,
                        "round": runtime.negotiation_round,
                        "task_id": intent.task_id,
                        "task_kind": intent.kind,
                        "agent_id": contract.agent_id,
                        "profile": contract.profile,
                        "contract_id": contract.contract_id,
                        "confidence": contract.confidence,
                        "estimated_latency_ms": contract.estimated_latency_ms,
                        "estimated_cost": contract.estimated_cost,
                    },
                )

                registration = registry.get(contract.agent_id)
                if registration is None:
                    raise RuntimeError(f"agent_not_registered:{contract.agent_id}")

                state_before_task = deepcopy(runtime.state)
                execution_state = self._build_execution_state_for_agent(
                    state=runtime.state,
                    registration=registration,
                    intent=intent,
                )
                execution_start = perf_counter()
                try:
                    next_state = await registration.node_fn(execution_state)
                except Exception as exc:
                    elapsed_ms = int(max(0.0, perf_counter() - execution_start) * 1000)
                    performance.executions += 1
                    performance.failures += 1
                    performance.total_latency_ms += elapsed_ms
                    realized_cost = self._realize_execution_cost(
                        contract=contract,
                        elapsed_ms=elapsed_ms,
                        approved=False,
                    )
                    self._apply_runtime_budget_spend(runtime=runtime, realized_cost=realized_cost)
                    budget_snapshot = self._build_runtime_budget_snapshot(runtime)
                    await self._publish_event(
                        runtime,
                        {
                            "type": "negotiation_budget_update",
                            "node": _COORDINATOR_NODE,
                            "round": runtime.negotiation_round,
                            "task_kind": intent.kind,
                            "agent_id": contract.agent_id,
                            **budget_snapshot,
                        },
                    )
                    if self._schedule_rebid(runtime=runtime, intent=intent, reason="execution_error"):
                        await self._publish_event(
                            runtime,
                            {
                                "type": "negotiation_rebid_scheduled",
                                "node": _COORDINATOR_NODE,
                                "round": runtime.negotiation_round,
                                "task_kind": intent.kind,
                                "reason": "execution_error",
                                "retry_count": int(runtime.task_retry_count.get(intent.kind) or 0),
                            },
                        )
                        continue
                    raise RuntimeError(f"agent_execution_failed:{intent.kind}:{str(exc)}") from exc

                if not isinstance(next_state, dict):
                    raise RuntimeError(f"invalid_agent_state:{intent.kind}")

                runtime.state = self._normalize_agent_output_state(
                    baseline_state=state_before_task,
                    execution_state=execution_state,
                    next_state=next_state,
                    registration=registration,
                    intent=intent,
                )
                runtime.updated_at = datetime.now(timezone.utc)
                elapsed_ms = int(max(0.0, perf_counter() - execution_start) * 1000)

                verdict = self._critic_review(
                    intent=intent,
                    contract=contract,
                    state_before=state_before_task,
                    state_after=runtime.state,
                )
                realized_cost = self._realize_execution_cost(
                    contract=contract,
                    elapsed_ms=elapsed_ms,
                    approved=verdict.approved,
                )
                self._apply_runtime_budget_spend(runtime=runtime, realized_cost=realized_cost)
                performance.executions += 1
                performance.total_latency_ms += elapsed_ms
                budget_snapshot = self._build_runtime_budget_snapshot(runtime)
                await self._publish_event(
                    runtime,
                    {
                        "type": "negotiation_budget_update",
                        "node": _COORDINATOR_NODE,
                        "round": runtime.negotiation_round,
                        "task_kind": intent.kind,
                        "agent_id": contract.agent_id,
                        **budget_snapshot,
                    },
                )

                if not verdict.approved:
                    performance.vetoes += 1
                    runtime.state = state_before_task
                    await self._publish_event(
                        runtime,
                        {
                            "type": "negotiation_critic_veto",
                            "node": _COORDINATOR_NODE,
                            "round": runtime.negotiation_round,
                            "task_id": intent.task_id,
                            "task_kind": intent.kind,
                            "agent_id": contract.agent_id,
                            "profile": contract.profile,
                            "reason": verdict.reason,
                            "severity": verdict.severity,
                        },
                    )
                    if self._schedule_rebid(runtime=runtime, intent=intent, reason=verdict.reason):
                        await self._publish_event(
                            runtime,
                            {
                                "type": "negotiation_rebid_scheduled",
                                "node": _COORDINATOR_NODE,
                                "round": runtime.negotiation_round,
                                "task_kind": intent.kind,
                                "reason": verdict.reason,
                                "retry_count": int(runtime.task_retry_count.get(intent.kind) or 0),
                            },
                        )
                        continue
                    raise RuntimeError(f"critic_rejected:{intent.kind}:{verdict.reason}")

                performance.successes += 1
                runtime.task_retry_count.pop(intent.kind, None)

                for next_kind in _TASK_TRANSITIONS.get(intent.kind, ()):
                    runtime.agenda.append(
                        self._build_task_intent(
                            kind=next_kind,
                            metadata={
                                "parent_task_id": intent.task_id,
                                "round": runtime.negotiation_round,
                            },
                        )
                    )

            if runtime.stop_requested:
                runtime.status = "stopped"
                await self._rollback_failed_history(runtime)
                await self._publish_event(runtime, {
                    "type": "stopped",
                    "message": "流程已停止。",
                })
                return

            await self._persist_completed_history(runtime)
            runtime.state["progress"] = 100
            runtime.status = "completed"
            runtime.updated_at = datetime.now(timezone.utc)
            await self._publish_event(
                runtime,
                {
                    "type": "session_complete",
                    "progress": int(runtime.state.get("progress") or 100),
                    "current_node": runtime.state.get("current_node") or "insight",
                    "report_id": runtime.state.get("report_id"),
                    "summary": "研究流程执行完成。",
                },
            )

        except PipelineStoppedError:
            runtime.status = "stopped"
            runtime.updated_at = datetime.now(timezone.utc)
            await self._rollback_failed_history(runtime)
            await self._publish_event(runtime, {
                "type": "stopped",
                "message": "流程已停止。",
            })
        except asyncio.CancelledError:
            runtime.status = "stopped"
            runtime.updated_at = datetime.now(timezone.utc)
            await self._rollback_failed_history(runtime)
            await self._publish_event(runtime, {
                "type": "stopped",
                "message": "流程已停止。",
            })
        except Exception as exc:  # noqa: BLE001
            runtime.status = "failed"
            runtime.updated_at = datetime.now(timezone.utc)
            runtime.error = str(exc)
            await self._rollback_failed_history(runtime)
            state_errors = list(runtime.state.get("errors") or [])
            state_errors.append(str(exc))
            runtime.state["errors"] = state_errors
            await self._publish_event(
                runtime,
                {
                    "type": "error",
                    "message": "Pipeline 执行失败。",
                    "error": str(exc),
                },
            )

    @staticmethod
    def _format_search_range_for_history(*, input_type: str, paper_range_years: Any) -> str:
        safe_input_type = str(input_type or "").strip().lower()
        if safe_input_type != "domain":
            return "-"
        try:
            years = int(paper_range_years) if paper_range_years is not None else 0
        except (TypeError, ValueError):
            years = 0
        if years > 0:
            return f"近 {years} 年"
        return "所有时间"

    @staticmethod
    def _build_history_pipeline_payload(state: PipelineState) -> dict[str, Any]:
        insight = state.get("insight") if isinstance(state.get("insight"), dict) else {}
        artifact = insight.get("artifact") if isinstance(insight.get("artifact"), dict) else {}
        return {
            "research_goal": state.get("research_goal") or "",
            "execution_plan": list(state.get("execution_plan") or []),
            "final_report": state.get("final_report") or "",
            "checkpoint_feedback": dict(state.get("checkpoint_feedback") or {}),
            "insight": {
                "status": str(insight.get("status") or ""),
                "summary": str(insight.get("summary") or ""),
                "language": str(insight.get("language") or ""),
                "agent_count": int(insight.get("agent_count") or 0),
                "exploration_depth": int(insight.get("exploration_depth") or 0),
                "agent_mode": str(insight.get("agent_mode") or ""),
                "markdown": str(insight.get("markdown") or ""),
                "artifact": {
                    "markdown_path": str(artifact.get("markdown_path") or ""),
                    "pdf_path": str(artifact.get("pdf_path") or ""),
                } if artifact else {},
                "generated_at": str(insight.get("generated_at") or ""),
            } if insight else {},
            "parallel_outputs_summary": {
                "research_gaps": len(state.get("research_gaps") or []),
                "critic_notes": len(state.get("critic_notes") or []),
            },
        }

    async def _persist_completed_history(self, runtime: _PipelineSessionRuntime) -> None:
        state = runtime.state
        graph_payload = state.get("graph_payload")
        if not isinstance(graph_payload, dict):
            state["history_id"] = None
            state["report_id"] = None
            return

        try:
            from models.schemas import KnowledgeGraphBuildRequest, KnowledgeGraphResponse
            from services.research_history_service import get_research_history_service

            history_service = get_research_history_service()
            user = UserProfile(
                id=str(runtime.user_id or "").strip(),
                email=str(state.get("user_email") or "").strip(),
                name=str(state.get("user_name") or "").strip(),
                picture=None,
            )

            graph = KnowledgeGraphResponse.model_validate(graph_payload)
            request = KnowledgeGraphBuildRequest(
                query=str(graph.query or state.get("input_value") or "").strip(),
                max_papers=min(30, max(3, len(state.get("papers") or []))),
                max_entities_per_paper=6,
                prefetched_papers=[],
                research_type=str(state.get("input_type") or "unknown"),
                search_input=str(state.get("input_value") or "").strip(),
                search_range=self._format_search_range_for_history(
                    input_type=str(state.get("input_type") or "domain"),
                    paper_range_years=state.get("paper_range_years"),
                ),
            )
            history_id = await asyncio.to_thread(
                history_service.record_graph_result,
                user=user,
                request=request,
                graph=graph,
            )
            safe_history_id = str(history_id or "").strip()
            if not safe_history_id:
                state["history_id"] = None
                state["report_id"] = None
                return

            await asyncio.to_thread(
                history_service.update_pipeline_payload,
                user=user,
                history_id=safe_history_id,
                pipeline_payload=self._build_history_pipeline_payload(state),
            )
            state["history_id"] = safe_history_id
            state["report_id"] = safe_history_id
        except Exception as exc:  # noqa: BLE001
            state_errors = list(state.get("errors") or [])
            state_errors.append(f"history_save_failed:{str(exc)}")
            state["errors"] = state_errors
            state["history_id"] = None
            state["report_id"] = None

    async def _rollback_failed_history(self, runtime: _PipelineSessionRuntime) -> None:
        safe_history_id = (
            str(runtime.state.get("history_id") or "").strip()
            or str(runtime.state.get("report_id") or "").strip()
        )
        if not safe_history_id:
            runtime.state["history_id"] = None
            runtime.state["report_id"] = None
            return

        try:
            from services.research_history_service import get_research_history_service

            history_service = get_research_history_service()
            rollback_user = UserProfile(
                id=str(runtime.user_id or "").strip(),
                email=str(runtime.state.get("user_email") or "").strip(),
                name=str(runtime.state.get("user_name") or "").strip(),
                picture=None,
            )
            await asyncio.to_thread(
                history_service.delete_history,
                user=rollback_user,
                history_id=safe_history_id,
            )
        except Exception:  # noqa: BLE001
            # Rollback failures should not mask the original pipeline failure.
            pass
        finally:
            runtime.state["history_id"] = None
            runtime.state["report_id"] = None

    def _resolve_agent_registry(self) -> dict[str, _AgentRegistration]:
        from agents.pipeline.nodes.checkpoints import human_checkpoint_1, human_checkpoint_2
        from agents.pipeline.nodes.graph_build import graph_build_node
        from agents.pipeline.nodes.insight import insight_node
        from agents.pipeline.nodes.planner import planner_node
        from agents.pipeline.nodes.router import router_node
        from agents.pipeline.nodes.search import search_node

        return {
            "planner_precise": _AgentRegistration(
                agent_id="planner_precise",
                task_kinds=("planner",),
                node_fn=planner_node,
                profile="precise",
                confidence_bias=0.05,
                cost_multiplier=1.08,
                latency_multiplier=1.12,
                critic_strictness=1.08,
            ),
            "planner_fast": _AgentRegistration(
                agent_id="planner_fast",
                task_kinds=("planner",),
                node_fn=planner_node,
                profile="fast",
                confidence_bias=-0.03,
                cost_multiplier=0.88,
                latency_multiplier=0.82,
                critic_strictness=0.92,
            ),
            "router_stable": _AgentRegistration(
                agent_id="router_stable",
                task_kinds=("router",),
                node_fn=router_node,
                profile="stable",
                confidence_bias=0.02,
                cost_multiplier=1.0,
                latency_multiplier=1.0,
                critic_strictness=1.0,
            ),
            "router_fast": _AgentRegistration(
                agent_id="router_fast",
                task_kinds=("router",),
                node_fn=router_node,
                profile="fast",
                confidence_bias=-0.02,
                cost_multiplier=0.82,
                latency_multiplier=0.78,
                critic_strictness=0.92,
            ),
            "search_recall": _AgentRegistration(
                agent_id="search_recall",
                task_kinds=("search",),
                node_fn=self._build_profiled_node_fn(search_node, profile="recall"),
                profile="recall",
                confidence_bias=0.05,
                cost_multiplier=1.26,
                latency_multiplier=1.18,
                critic_strictness=1.12,
            ),
            "search_fast": _AgentRegistration(
                agent_id="search_fast",
                task_kinds=("search",),
                node_fn=self._build_profiled_node_fn(search_node, profile="fast"),
                profile="fast",
                confidence_bias=-0.01,
                cost_multiplier=0.82,
                latency_multiplier=0.74,
                critic_strictness=0.92,
            ),
            "search_budget": _AgentRegistration(
                agent_id="search_budget",
                task_kinds=("search",),
                node_fn=self._build_profiled_node_fn(search_node, profile="budget"),
                profile="budget",
                confidence_bias=-0.06,
                cost_multiplier=0.68,
                latency_multiplier=0.72,
                critic_strictness=0.86,
            ),
            "graph_build_dense": _AgentRegistration(
                agent_id="graph_build_dense",
                task_kinds=("graph_build",),
                node_fn=self._build_profiled_node_fn(graph_build_node, profile="dense"),
                profile="dense",
                confidence_bias=0.04,
                cost_multiplier=1.22,
                latency_multiplier=1.2,
                critic_strictness=1.14,
            ),
            "graph_build_balanced": _AgentRegistration(
                agent_id="graph_build_balanced",
                task_kinds=("graph_build",),
                node_fn=self._build_profiled_node_fn(graph_build_node, profile="balanced"),
                profile="balanced",
                confidence_bias=0.01,
                cost_multiplier=1.0,
                latency_multiplier=1.0,
                critic_strictness=1.0,
            ),
            "graph_build_lean": _AgentRegistration(
                agent_id="graph_build_lean",
                task_kinds=("graph_build",),
                node_fn=self._build_profiled_node_fn(graph_build_node, profile="lean"),
                profile="lean",
                confidence_bias=-0.05,
                cost_multiplier=0.76,
                latency_multiplier=0.78,
                critic_strictness=0.9,
            ),
            "checkpoint_1_guarded": _AgentRegistration(
                agent_id="checkpoint_1_guarded",
                task_kinds=("checkpoint_1",),
                node_fn=human_checkpoint_1,
                profile="guarded",
                confidence_bias=0.03,
                cost_multiplier=1.05,
                latency_multiplier=1.08,
                critic_strictness=1.08,
            ),
            "checkpoint_1_quickpass": _AgentRegistration(
                agent_id="checkpoint_1_quickpass",
                task_kinds=("checkpoint_1",),
                node_fn=human_checkpoint_1,
                profile="quickpass",
                confidence_bias=-0.03,
                cost_multiplier=0.86,
                latency_multiplier=0.85,
                critic_strictness=0.92,
            ),
            "checkpoint_2_guarded": _AgentRegistration(
                agent_id="checkpoint_2_guarded",
                task_kinds=("checkpoint_2",),
                node_fn=human_checkpoint_2,
                profile="guarded",
                confidence_bias=0.03,
                cost_multiplier=1.06,
                latency_multiplier=1.08,
                critic_strictness=1.08,
            ),
            "checkpoint_2_fastpass": _AgentRegistration(
                agent_id="checkpoint_2_fastpass",
                task_kinds=("checkpoint_2",),
                node_fn=human_checkpoint_2,
                profile="quickpass",
                confidence_bias=-0.02,
                cost_multiplier=0.88,
                latency_multiplier=0.86,
                critic_strictness=0.92,
            ),
            "insight_balanced": _AgentRegistration(
                agent_id="insight_balanced",
                task_kinds=("insight",),
                node_fn=self._build_profiled_node_fn(insight_node, profile="balanced"),
                profile="balanced",
                confidence_bias=0.01,
                cost_multiplier=1.0,
                latency_multiplier=1.0,
                critic_strictness=1.0,
            ),
            "insight_breadth": _AgentRegistration(
                agent_id="insight_breadth",
                task_kinds=("insight",),
                node_fn=self._build_profiled_node_fn(insight_node, profile="recall"),
                profile="recall",
                confidence_bias=0.03,
                cost_multiplier=1.22,
                latency_multiplier=1.16,
                critic_strictness=1.1,
            ),
            "insight_lean": _AgentRegistration(
                agent_id="insight_lean",
                task_kinds=("insight",),
                node_fn=self._build_profiled_node_fn(insight_node, profile="budget"),
                profile="budget",
                confidence_bias=-0.05,
                cost_multiplier=0.76,
                latency_multiplier=0.78,
                critic_strictness=0.88,
            ),
        }

    def _build_task_intent(self, *, kind: str, metadata: dict[str, Any] | None = None) -> _TaskIntent:
        safe_kind = str(kind or "").strip().lower()
        now = datetime.now(timezone.utc)
        return _TaskIntent(
            task_id=f"task-{safe_kind}-{uuid4().hex[:8]}",
            kind=safe_kind,
            priority=_TASK_PRIORITY.get(safe_kind, 1),
            created_at=now,
            metadata=dict(metadata or {}),
        )

    def _build_profiled_node_fn(self, node_fn: NodeCallable, *, profile: str) -> NodeCallable:
        # Profile behavior is applied by runtime before and after the node call.
        return node_fn

    def _build_execution_state_for_agent(
        self,
        *,
        state: PipelineState,
        registration: _AgentRegistration,
        intent: _TaskIntent,
    ) -> PipelineState:
        execution_state = deepcopy(state)
        task_kind = str(intent.kind or "").strip().lower()
        profile = self._normalize_profile_alias(registration.profile)

        if task_kind == "search":
            if profile in {"fast", "budget"}:
                execution_state["quick_mode"] = True
            if profile == "recall":
                execution_state["quick_mode"] = False

        if task_kind == "graph_build":
            papers = self._sort_papers_by_signal(execution_state.get("papers") or [])
            if profile == "lean":
                execution_state["papers"] = papers[:16]
            elif profile == "dense":
                execution_state["papers"] = papers[:30]
            else:
                execution_state["papers"] = papers[:24] if len(papers) > 24 else papers

        if task_kind == "insight":
            config = dict(execution_state.get("insight_config") or {})
            try:
                base_agent_count = int(config.get("agent_count") or 4)
            except (TypeError, ValueError):
                base_agent_count = 4
            try:
                base_depth = int(config.get("exploration_depth") or 2)
            except (TypeError, ValueError):
                base_depth = 2
            base_language = str(config.get("report_language") or "zh").strip().lower()
            if base_language not in {"zh", "en"}:
                base_language = "zh"
            base_mode = str(config.get("agent_mode") or "orchestrated").strip().lower()
            if base_mode not in {"legacy", "orchestrated"}:
                base_mode = "orchestrated"
            if profile in {"budget", "lean", "fast"}:
                config["agent_count"] = max(2, min(8, base_agent_count - 1))
                config["exploration_depth"] = max(1, min(5, base_depth - 1))
            elif profile in {"recall", "dense"}:
                config["agent_count"] = max(2, min(8, base_agent_count + 1))
                config["exploration_depth"] = max(1, min(5, base_depth + 1))
            else:
                config["agent_count"] = max(2, min(8, base_agent_count))
                config["exploration_depth"] = max(1, min(5, base_depth))
            config["report_language"] = base_language
            config["agent_mode"] = base_mode
            execution_state["insight_config"] = config

        return execution_state

    def _normalize_agent_output_state(
        self,
        *,
        baseline_state: PipelineState,
        execution_state: PipelineState,
        next_state: PipelineState,
        registration: _AgentRegistration,
        intent: _TaskIntent,
    ) -> PipelineState:
        _ = execution_state
        normalized_state = dict(next_state)
        task_kind = str(intent.kind or "").strip().lower()

        # Keep stable session-level controls; strategy-specific mutations are execution-only.
        normalized_state["quick_mode"] = bool(baseline_state.get("quick_mode"))
        normalized_state["paper_range_years"] = baseline_state.get("paper_range_years")

        # Preserve full retrieval corpus for downstream stages when graph build chooses lean subsets.
        if task_kind == "graph_build":
            normalized_state["papers"] = list(baseline_state.get("papers") or [])
            normalized_state["seed_paper"] = baseline_state.get("seed_paper")

        normalized_state["messages"] = list(normalized_state.get("messages") or [])
        return normalized_state  # type: ignore[return-value]

    @staticmethod
    def _sort_papers_by_signal(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        safe_papers = [dict(item) for item in papers if isinstance(item, dict)]
        safe_papers.sort(
            key=lambda item: (
                int(item.get("citation_count") or 0),
                int(item.get("year") or 0),
            ),
            reverse=True,
        )
        return safe_papers

    @staticmethod
    def _normalize_profile_alias(profile: str) -> str:
        safe_profile = str(profile or "").strip().lower()
        if safe_profile in {"fast", "quick", "quickpass"}:
            return "fast"
        if safe_profile in {"balanced", "stable"}:
            return "balanced"
        return safe_profile

    def _resolve_session_budget(self, *, input_type: str, quick_mode: bool) -> float:
        # Reserve a larger baseline budget so the workflow can consistently
        # complete through checkpoint_2 + insight even with retries/rebids.
        base = 20.0 if quick_mode else 26.0
        safe_input_type = str(input_type or "").strip().lower()
        if safe_input_type in {"arxiv_id", "doi"}:
            base += 1.5
        return round(base, 3)

    def _collect_bids(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        registry: dict[str, _AgentRegistration],
    ) -> list[_AgentBid]:
        bids: list[_AgentBid] = []
        for registration in registry.values():
            if intent.kind not in registration.task_kinds:
                continue

            confidence = self._compute_dynamic_confidence(
                runtime=runtime,
                intent=intent,
                registration=registration,
            )
            estimated_latency_ms = self._estimate_bid_latency(
                runtime=runtime,
                intent=intent,
                registration=registration,
            )
            estimated_cost = self._estimate_bid_cost(
                runtime=runtime,
                intent=intent,
                registration=registration,
            )
            retry_count = int(intent.metadata.get("retry_count") or 0)
            bids.append(
                _AgentBid(
                    bid_id=f"bid-{registration.agent_id}-{uuid4().hex[:6]}",
                    task_id=intent.task_id,
                    task_kind=intent.kind,
                    agent_id=registration.agent_id,
                    confidence=confidence,
                    estimated_latency_ms=estimated_latency_ms,
                    estimated_cost=estimated_cost,
                    profile=registration.profile,
                    rationale=(
                        f"{registration.agent_id} 支持任务 {intent.kind}，"
                        f"置信度 {confidence:.3f}，"
                        f"预计耗时 {estimated_latency_ms}ms，"
                        f"预计成本 {estimated_cost:.3f}，"
                        f"重试次数 {retry_count}。"
                    ),
                    submitted_at=datetime.now(timezone.utc),
                )
            )

        bids.sort(
            key=lambda item: (
                -float(item.confidence),
                float(item.estimated_cost),
                int(item.estimated_latency_ms),
                item.agent_id,
            )
        )
        return bids

    def _compute_dynamic_confidence(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        registration: _AgentRegistration,
    ) -> float:
        task_kind = str(intent.kind or "").strip().lower()
        base = float(_TASK_BASE_CONFIDENCE.get(task_kind, 0.75))
        base += float(registration.confidence_bias)
        base += (float(registration.critic_strictness) - 1.0) * 0.02

        performance = runtime.agent_performance.get(registration.agent_id)
        if performance and performance.executions > 0:
            success_rate = float(performance.successes) / float(max(1, performance.executions))
            base += (success_rate - 0.55) * 0.24
            base -= min(0.22, float(performance.vetoes) * 0.05)
            base -= min(0.24, float(performance.failures) * 0.07)
            average_latency = float(performance.total_latency_ms) / float(max(1, performance.executions))
            base_latency = float(_TASK_ESTIMATED_LATENCY_MS.get(task_kind, 1200))
            if average_latency > base_latency * 1.5:
                base -= 0.04

        base += self._state_alignment_delta(task_kind=task_kind, state=runtime.state)

        retry_count = int(intent.metadata.get("retry_count") or runtime.task_retry_count.get(task_kind) or 0)
        base -= min(0.28, retry_count * 0.09)

        if bool(runtime.state.get("quick_mode")) and self._normalize_profile_alias(registration.profile) == "fast":
            base += 0.04
        if (not bool(runtime.state.get("quick_mode"))) and self._normalize_profile_alias(registration.profile) in {"dense", "recall"}:
            base += 0.03

        budget_limit = max(0.01, float(runtime.budget_limit))
        remaining_ratio = max(0.0, (budget_limit - float(runtime.budget_spent)) / budget_limit)
        if remaining_ratio < 0.35:
            base -= 0.05
        if remaining_ratio < 0.20:
            base -= 0.09

        return round(max(0.05, min(0.99, base)), 3)

    def _state_alignment_delta(self, *, task_kind: str, state: PipelineState) -> float:
        safe_kind = str(task_kind or "").strip().lower()
        papers = list(state.get("papers") or [])

        if safe_kind == "planner":
            return 0.02 if str(state.get("input_value") or "").strip() else -0.20
        if safe_kind == "router":
            return 0.01
        if safe_kind == "search":
            return 0.04 if str(state.get("research_goal") or "").strip() else -0.10
        if safe_kind == "graph_build":
            return 0.06 if papers else -0.15
        if safe_kind == "checkpoint_1":
            return 0.04 if papers else -0.10
        if safe_kind == "checkpoint_2":
            graph_payload = state.get("graph_payload")
            node_count = len((graph_payload or {}).get("nodes") or []) if isinstance(graph_payload, dict) else 0
            return 0.05 if node_count > 0 else -0.12
        if safe_kind == "insight":
            graph_payload = state.get("graph_payload")
            node_count = len((graph_payload or {}).get("nodes") or []) if isinstance(graph_payload, dict) else 0
            config = dict(state.get("insight_config") or {})
            try:
                agent_count = int(config.get("agent_count") or 0)
            except (TypeError, ValueError):
                agent_count = 0
            try:
                exploration_depth = int(config.get("exploration_depth") or 0)
            except (TypeError, ValueError):
                exploration_depth = 0
            agent_mode = str(config.get("agent_mode") or "").strip().lower()
            report_language = str(config.get("report_language") or "").strip().lower()
            has_valid_config = (
                2 <= agent_count <= 8
                and 1 <= exploration_depth <= 5
                and report_language in {"zh", "en"}
                and agent_mode in {"legacy", "orchestrated"}
            )
            score = 0.02
            if node_count > 0:
                score += 0.03
            if has_valid_config:
                score += 0.03
            return score
        return 0.0

    def _estimate_bid_cost(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        registration: _AgentRegistration,
    ) -> float:
        task_kind = str(intent.kind or "").strip().lower()
        base_cost = float(_TASK_ESTIMATED_COST.get(task_kind, 0.4))
        retry_count = int(intent.metadata.get("retry_count") or runtime.task_retry_count.get(task_kind) or 0)
        paper_count = len(runtime.state.get("papers") or [])
        keyword_count = len(runtime.state.get("search_keywords") or [])
        complexity = 1.0

        if task_kind == "graph_build":
            complexity += min(0.60, float(paper_count) / 60.0)
        elif task_kind == "search":
            complexity += min(0.30, float(keyword_count) / 20.0)
        elif task_kind == "insight":
            config = dict(runtime.state.get("insight_config") or {})
            try:
                agent_count = int(config.get("agent_count") or 4)
            except (TypeError, ValueError):
                agent_count = 4
            try:
                depth = int(config.get("exploration_depth") or 2)
            except (TypeError, ValueError):
                depth = 2
            agent_count = max(2, min(8, agent_count))
            depth = max(1, min(5, depth))
            complexity += min(0.85, float(agent_count) / 10.0 + float(depth) / 8.0)
            complexity += min(0.35, float(paper_count) / 90.0)

        if bool(runtime.state.get("quick_mode")):
            complexity *= 0.88

        multiplier = float(registration.cost_multiplier) * (1.0 + min(0.80, retry_count * 0.22))
        estimated = base_cost * complexity * multiplier
        return round(max(0.03, estimated), 4)

    def _estimate_bid_latency(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        registration: _AgentRegistration,
    ) -> int:
        task_kind = str(intent.kind or "").strip().lower()
        base_latency = float(_TASK_ESTIMATED_LATENCY_MS.get(task_kind, 1200))
        retry_count = int(intent.metadata.get("retry_count") or runtime.task_retry_count.get(task_kind) or 0)
        paper_count = len(runtime.state.get("papers") or [])
        multiplier = float(registration.latency_multiplier) * (1.0 + min(0.40, retry_count * 0.16))
        if task_kind == "graph_build":
            multiplier += min(0.35, float(paper_count) / 80.0)
        elif task_kind == "insight":
            config = dict(runtime.state.get("insight_config") or {})
            try:
                agent_count = int(config.get("agent_count") or 4)
            except (TypeError, ValueError):
                agent_count = 4
            try:
                depth = int(config.get("exploration_depth") or 2)
            except (TypeError, ValueError):
                depth = 2
            agent_count = max(2, min(8, agent_count))
            depth = max(1, min(5, depth))
            multiplier += min(0.95, float(agent_count - 1) * 0.10 + float(depth - 1) * 0.15)
            multiplier += min(0.28, float(paper_count) / 110.0)
        return max(1, int(base_latency * multiplier))

    def _select_winning_bid(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        bids: list[_AgentBid],
    ) -> _AgentBid | None:
        if not bids:
            return None

        affordable = [
            item
            for item in bids
            if self._is_bid_budget_feasible(runtime=runtime, intent=intent, bid=item)
        ]
        task_kind = str(intent.kind or "").strip().lower()
        if not affordable and task_kind == "search":
            affordable = [
                item
                for item in bids
                if self._is_bid_within_hard_budget(runtime=runtime, bid=item)
            ]
        if not affordable and task_kind == "search":
            remaining_budget = float(runtime.budget_limit) - float(runtime.budget_spent)
            if remaining_budget > 0:
                max_overrun = 0.45
                fallback_candidates = sorted(
                    bids,
                    key=lambda item: (
                        float(item.estimated_cost),
                        int(item.estimated_latency_ms),
                        -float(item.confidence),
                        item.agent_id,
                    ),
                )
                for candidate in fallback_candidates:
                    overrun = float(candidate.estimated_cost) - remaining_budget
                    if overrun <= max_overrun + 1e-9:
                        affordable = [candidate]
                        break
        if not affordable:
            return None

        affordable.sort(
            key=lambda item: (
                -self._score_bid(runtime=runtime, bid=item),
                -float(item.confidence),
                float(item.estimated_cost),
                int(item.estimated_latency_ms),
                item.agent_id,
            )
        )
        return affordable[0]

    def _is_bid_budget_feasible(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        bid: _AgentBid,
    ) -> bool:
        task_kind = str(intent.kind or "").strip().lower()
        spend_after_award = float(runtime.budget_spent) + float(bid.estimated_cost)
        if task_kind == "checkpoint_1":
            return self._is_bid_within_hard_budget(runtime=runtime, bid=bid)
        reserve = self._estimate_reserved_downstream_cost(task_kind=intent.kind)
        return spend_after_award + reserve <= float(runtime.budget_limit) + 1e-9

    def _is_bid_within_hard_budget(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        bid: _AgentBid,
    ) -> bool:
        spend_after_award = float(runtime.budget_spent) + float(bid.estimated_cost)
        return spend_after_award <= float(runtime.budget_limit) + 1e-9

    def _estimate_reserved_downstream_cost(self, *, task_kind: str) -> float:
        safe_task_kind = str(task_kind or "").strip().lower()
        cursor = safe_task_kind
        visited: set[str] = set()
        reserve = 0.0
        while True:
            next_items = _TASK_TRANSITIONS.get(cursor, ())
            if not next_items:
                break
            next_kind = str(next_items[0] or "").strip().lower()
            if not next_kind or next_kind in visited:
                break
            visited.add(next_kind)
            reserve += float(_TASK_ESTIMATED_COST.get(next_kind, 0.2))
            cursor = next_kind
        return round(max(0.0, reserve), 4)

    def _score_bid(self, *, runtime: _PipelineSessionRuntime, bid: _AgentBid) -> float:
        remaining = max(0.01, float(runtime.budget_limit) - float(runtime.budget_spent))
        cost_ratio = min(3.0, float(bid.estimated_cost) / remaining)
        latency_ratio = min(3.0, float(bid.estimated_latency_ms) / 10000.0)
        performance = runtime.agent_performance.get(bid.agent_id)
        exploration_bonus = 0.03
        veto_penalty = 0.0
        if performance:
            exploration_bonus = max(0.0, 0.03 - float(performance.awards) * 0.004)
            veto_penalty = min(0.08, float(performance.vetoes) * 0.02)
        profile = self._normalize_profile_alias(bid.profile)
        mode_alignment = 0.0
        if bool(runtime.state.get("quick_mode")) and profile == "fast":
            mode_alignment += 0.03
        if (not bool(runtime.state.get("quick_mode"))) and profile in {"recall", "dense", "balanced"}:
            mode_alignment += 0.02
        return (
            float(bid.confidence) * 1.0
            - cost_ratio * 0.22
            - latency_ratio * 0.12
            - veto_penalty
            + exploration_bonus
            + mode_alignment
        )

    def _schedule_rebid(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        reason: str,
    ) -> bool:
        task_kind = str(intent.kind or "").strip().lower()
        current_retry = int(runtime.task_retry_count.get(task_kind) or 0)
        if current_retry >= int(runtime.max_rebid_per_task):
            return False

        next_retry = current_retry + 1
        runtime.task_retry_count[task_kind] = next_retry
        metadata = dict(intent.metadata or {})
        metadata.update(
            {
                "retry_count": next_retry,
                "retry_reason": str(reason or "").strip() or "unknown",
                "retry_of_task_id": intent.task_id,
            }
        )
        runtime.agenda.append(
            _TaskIntent(
                task_id=f"task-{task_kind}-retry-{uuid4().hex[:8]}",
                kind=task_kind,
                priority=max(1, int(intent.priority) + 1),
                created_at=datetime.now(timezone.utc),
                metadata=metadata,
            )
        )
        return True

    def _critic_review(
        self,
        *,
        intent: _TaskIntent,
        contract: _TaskContract,
        state_before: PipelineState,
        state_after: PipelineState,
    ) -> _CriticVerdict:
        task_kind = str(intent.kind or "").strip().lower()
        profile = self._normalize_profile_alias(contract.profile)
        strictness = max(0.7, min(1.35, float(self._resolve_profile_strictness(profile))))
        before_errors = len(state_before.get("errors") or [])
        after_errors = len(state_after.get("errors") or [])
        if after_errors > before_errors:
            return _CriticVerdict(
                approved=False,
                reason="任务执行新增错误记录，需重试。",
                severity="warning",
            )

        if task_kind == "planner":
            goal = str(state_after.get("research_goal") or "").strip()
            execution_plan = list(state_after.get("execution_plan") or [])
            required_steps = 3 if strictness >= 1.05 else 2
            if not goal or len(execution_plan) < required_steps:
                return _CriticVerdict(False, "研究目标或执行计划不完整。", "warning")
            return _CriticVerdict(True, "规划产物完整。")

        if task_kind == "router":
            if str(state_after.get("current_node") or "").strip().lower() != "router":
                return _CriticVerdict(False, "路由节点状态异常。", "warning")
            return _CriticVerdict(True, "路由状态正常。")

        if task_kind == "search":
            papers = list(state_after.get("papers") or [])
            if not papers:
                return _CriticVerdict(False, "未检索到候选论文。", "warning")
            requested_range = self._normalize_year_range(state_after.get("paper_range_years"))
            fallback_applied = bool(state_after.get("search_fallback_applied"))
            minimum_papers = 6 if strictness < 0.95 else 8
            if profile in {"recall", "dense"}:
                minimum_papers = max(minimum_papers, 10)
            if requested_range is not None and requested_range <= 1:
                minimum_papers = min(minimum_papers, 4)
            elif requested_range is not None and requested_range <= 2:
                minimum_papers = min(minimum_papers, 5)
            if fallback_applied:
                minimum_papers = min(minimum_papers, 4)
            if len(papers) < minimum_papers:
                return _CriticVerdict(False, f"候选论文数量不足（{len(papers)} 篇）。", "warning")
            if fallback_applied and len(papers) < 8:
                return _CriticVerdict(True, f"检索产物偏少（{len(papers)} 篇），已按放宽范围继续。")
            return _CriticVerdict(True, f"检索产物可用（{len(papers)} 篇）。")

        if task_kind == "graph_build":
            graph_payload = state_after.get("graph_payload")
            node_count = len((graph_payload or {}).get("nodes") or []) if isinstance(graph_payload, dict) else 0
            min_nodes = 6 if strictness >= 1.0 else 4
            if profile == "dense":
                min_nodes = max(min_nodes, 10)
            if not isinstance(graph_payload, dict) or node_count < min_nodes:
                return _CriticVerdict(False, "知识图谱结构不完整。", "warning")
            return _CriticVerdict(True, f"图谱产物可用（{node_count} 个节点）。")

        if task_kind == "checkpoint_1":
            if str(state_after.get("current_node") or "").strip().lower() != "checkpoint_1":
                return _CriticVerdict(False, "检查点状态未更新。", "warning")
            return _CriticVerdict(True, "检查点确认完成。")

        if task_kind == "checkpoint_2":
            if str(state_after.get("current_node") or "").strip().lower() != "checkpoint_2":
                return _CriticVerdict(False, "探索检查点状态未更新。", "warning")
            config = dict(state_after.get("insight_config") or {})
            try:
                agent_count = int(config.get("agent_count") or 0)
                depth = int(config.get("exploration_depth") or 0)
            except (TypeError, ValueError):
                return _CriticVerdict(False, "探索参数解析失败。", "warning")
            mode = str(config.get("agent_mode") or "").strip().lower()
            report_language = str(config.get("report_language") or "").strip().lower()
            if mode not in {"legacy", "orchestrated"}:
                return _CriticVerdict(False, "探索模式参数非法。", "warning")
            if report_language not in {"zh", "en"}:
                return _CriticVerdict(False, "探索报告语言参数非法。", "warning")
            if not (2 <= agent_count <= 8 and 1 <= depth <= 5):
                return _CriticVerdict(False, "探索参数超出允许范围。", "warning")
            return _CriticVerdict(True, "探索参数确认完成。")

        if task_kind == "insight":
            insight = state_after.get("insight")
            if not isinstance(insight, dict):
                return _CriticVerdict(False, "探索产物缺失。", "warning")
            markdown = str(insight.get("markdown") or "").strip()
            summary = str(insight.get("summary") or "").strip()
            agent_mode = str(insight.get("agent_mode") or "").strip().lower()
            if agent_mode not in {"legacy", "orchestrated"}:
                return _CriticVerdict(False, "探索模式信息缺失。", "warning")
            min_length = 700 if strictness >= 1.05 else 420
            if len(markdown) < min_length:
                return _CriticVerdict(False, "探索报告内容不足。", "warning")
            if not summary:
                return _CriticVerdict(False, "探索摘要缺失。", "warning")
            artifact = insight.get("artifact") if isinstance(insight.get("artifact"), dict) else {}
            markdown_path = str(artifact.get("markdown_path") or "").strip()
            if not markdown_path:
                return _CriticVerdict(False, "探索报告文件未生成。", "warning")
            return _CriticVerdict(True, "探索洞察产物可用。")

        return _CriticVerdict(True, "无需审核。")

    @staticmethod
    def _resolve_profile_strictness(profile: str) -> float:
        safe_profile = str(profile or "").strip().lower()
        if safe_profile in {"dense", "recall", "precise", "guarded"}:
            return 1.12
        if safe_profile in {"lean", "budget", "fast", "quickpass"}:
            return 0.9
        return 1.0

    @staticmethod
    def _normalize_year_range(raw_value: Any) -> int | None:
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return min(30, parsed)

    def _realize_execution_cost(
        self,
        *,
        contract: _TaskContract,
        elapsed_ms: int,
        approved: bool,
    ) -> float:
        base = float(contract.estimated_cost)
        expected_latency = max(1, int(contract.estimated_latency_ms))
        ratio = float(max(0, int(elapsed_ms))) / float(expected_latency)
        multiplier = 1.0
        if ratio > 1.0:
            multiplier += min(0.35, (ratio - 1.0) * 0.25)
        if not approved:
            multiplier += 0.10
        return round(max(0.02, base * multiplier), 4)

    def _award_contract(
        self,
        *,
        runtime: _PipelineSessionRuntime,
        intent: _TaskIntent,
        bid: _AgentBid,
    ) -> _TaskContract:
        return _TaskContract(
            contract_id=f"contract-{intent.kind}-{uuid4().hex[:8]}",
            task_id=intent.task_id,
            task_kind=intent.kind,
            agent_id=bid.agent_id,
            confidence=bid.confidence,
            estimated_latency_ms=bid.estimated_latency_ms,
            estimated_cost=bid.estimated_cost,
            profile=bid.profile,
            round_index=runtime.negotiation_round,
            awarded_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _apply_runtime_budget_spend(*, runtime: _PipelineSessionRuntime, realized_cost: float) -> None:
        safe_cost = max(0.0, float(realized_cost))
        budget_limit = max(0.0, float(runtime.budget_limit))
        runtime.budget_spent = min(budget_limit, float(runtime.budget_spent) + safe_cost)

    @staticmethod
    def _build_runtime_budget_snapshot(runtime: _PipelineSessionRuntime) -> dict[str, float]:
        spent = round(max(0.0, float(runtime.budget_spent)), 4)
        limit = round(max(0.0, float(runtime.budget_limit)), 4)
        remaining = round(max(0.0, float(runtime.budget_limit) - float(runtime.budget_spent)), 4)
        return {
            "spent": spent,
            "limit": limit,
            "remaining": remaining,
        }

    @staticmethod
    def _is_runtime_active(runtime: _PipelineSessionRuntime) -> bool:
        return str(runtime.status or "").strip().lower() not in _FINAL_STATUSES

    def _find_active_runtime_for_user_locked(self, user_id: str) -> _PipelineSessionRuntime | None:
        safe_user_id = str(user_id or "").strip()
        if not safe_user_id:
            return None
        candidates = [
            runtime
            for runtime in self._sessions.values()
            if runtime.user_id == safe_user_id and self._is_runtime_active(runtime)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.updated_at, reverse=True)
        return candidates[0]

    async def get_active_session_snapshot(self, user_id: str) -> dict[str, Any] | None:
        async with self._sessions_lock:
            runtime = self._find_active_runtime_for_user_locked(user_id)
        if runtime is None:
            return None
        return {
            "session_id": runtime.session_id,
            "status": runtime.status,
            "waiting_checkpoint": runtime.waiting_checkpoint or "",
            "state": runtime.state,
            "created_at": runtime.created_at.isoformat(),
            "updated_at": runtime.updated_at.isoformat(),
        }

    async def can_access(self, session_id: str, user_id: str) -> bool:
        runtime = await self._get_runtime(session_id)
        return bool(runtime and runtime.user_id == user_id)

    async def emit_node_start(self, session_id: str, node: str, progress: int) -> None:
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "node_start",
                "node": str(node),
                "progress": int(progress),
            },
        )

    async def emit_thinking(self, session_id: str, node: str, content: str) -> None:
        safe_content = str(content or "").strip()
        if not safe_content:
            return
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "thinking",
                "node": str(node),
                "content": safe_content,
            },
        )

    async def emit_insight_stream(
        self,
        session_id: str,
        *,
        section: str,
        chunk: str,
        accumulated_chars: int,
        done: bool = False,
    ) -> None:
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "insight_stream",
                "node": "insight",
                "section": str(section or "insight_markdown"),
                "chunk": str(chunk or ""),
                "accumulated_chars": max(0, int(accumulated_chars or 0)),
                "done": bool(done),
            },
        )

    async def emit_insight_orchestrator_event(
        self,
        session_id: str,
        *,
        event: dict[str, Any],
    ) -> None:
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "insight_orchestrator_event",
                "node": "insight",
                "event": dict(event or {}),
            },
        )

    async def emit_node_complete(
        self,
        session_id: str,
        node: str,
        progress: int,
        summary: str,
    ) -> None:
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "node_complete",
                "node": str(node),
                "progress": int(progress),
                "summary": str(summary or ""),
            },
        )

    async def wait_for_checkpoint(
        self,
        session_id: str,
        *,
        checkpoint: str,
        message: str,
        timeout_seconds: int | None = 30,
    ) -> str:
        runtime = await self._require_runtime(session_id)
        await self.ensure_active(session_id)

        runtime.waiting_checkpoint = checkpoint
        runtime.resume_event = asyncio.Event()
        runtime.resume_feedback = ""
        await self._publish_event(
            runtime,
            {
                "type": "pause",
                "checkpoint": checkpoint,
                "message": str(message or ""),
                "timeout": 0 if timeout_seconds is None or int(timeout_seconds) <= 0 else max(1, int(timeout_seconds)),
            },
        )

        try:
            if timeout_seconds is None or int(timeout_seconds) <= 0:
                await runtime.resume_event.wait()
                feedback = runtime.resume_feedback
            else:
                await asyncio.wait_for(runtime.resume_event.wait(), timeout=max(1, int(timeout_seconds)))
                feedback = runtime.resume_feedback
        except TimeoutError:
            feedback = ""
        else:
            if timeout_seconds is None or int(timeout_seconds) <= 0:
                feedback = runtime.resume_feedback
        finally:
            runtime.waiting_checkpoint = None
            runtime.resume_event = None
            runtime.resume_feedback = ""

        if runtime.stop_requested:
            raise PipelineStoppedError("pipeline_stopped")
        return feedback

    async def resume_session(self, session_id: str, user_id: str, feedback: str) -> tuple[bool, str]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        if runtime.status in _FINAL_STATUSES:
            return False, "session_closed"
        runtime.budget_limit = max(
            float(runtime.budget_limit),
            self._resolve_session_budget(
                input_type=str(runtime.state.get("input_type") or "").strip().lower(),
                quick_mode=bool(runtime.state.get("quick_mode")),
            ),
        )
        if runtime.waiting_checkpoint is None or runtime.resume_event is None:
            return False, "no_pending_checkpoint"

        runtime.resume_feedback = str(feedback or "").strip()
        runtime.resume_event.set()
        await self._publish_event(
            runtime,
            {
                "type": "thinking",
                "node": runtime.waiting_checkpoint,
                "content": "已收到反馈，流程继续执行。",
            },
        )
        return True, "resumed"

    async def stop_session(self, session_id: str, user_id: str) -> bool:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        if runtime.status in _FINAL_STATUSES:
            return False

        runtime.stop_requested = True
        runtime.updated_at = datetime.now(timezone.utc)

        if runtime.resume_event is not None:
            runtime.resume_event.set()
        if runtime.task and not runtime.task.done():
            runtime.task.cancel()
        return True

    async def ensure_active(self, session_id: str) -> None:
        runtime = await self._require_runtime(session_id)
        if runtime.stop_requested:
            raise PipelineStoppedError("pipeline_stopped")

    async def get_session_state(self, session_id: str, user_id: str) -> tuple[PipelineState, str]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        return runtime.state, runtime.status

    async def get_session_snapshot(self, session_id: str, user_id: str) -> dict[str, Any]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        return {
            "session_id": runtime.session_id,
            "status": runtime.status,
            "waiting_checkpoint": runtime.waiting_checkpoint or "",
            "state": runtime.state,
            "created_at": runtime.created_at.isoformat(),
            "updated_at": runtime.updated_at.isoformat(),
        }

    async def stream_events(
        self,
        session_id: str,
        user_id: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")

        cursor = 0
        while True:
            async with runtime.event_condition:
                await runtime.event_condition.wait_for(
                    lambda: cursor < len(runtime.events) or runtime.status in _FINAL_STATUSES
                )
                pending = list(runtime.events[cursor:])
                cursor = len(runtime.events)
                is_final = runtime.status in _FINAL_STATUSES

            for event in pending:
                yield event

            if is_final and cursor >= len(runtime.events):
                break

    async def _publish_event(self, runtime: _PipelineSessionRuntime, event: dict[str, Any]) -> None:
        payload = {
            "session_id": runtime.session_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        runtime.events.append(payload)
        runtime.updated_at = datetime.now(timezone.utc)
        async with runtime.event_condition:
            runtime.event_condition.notify_all()

    async def _get_runtime(self, session_id: str) -> _PipelineSessionRuntime | None:
        async with self._sessions_lock:
            return self._sessions.get(session_id)

    async def _require_runtime(self, session_id: str) -> _PipelineSessionRuntime:
        runtime = await self._get_runtime(session_id)
        if runtime is None:
            raise PipelineRuntimeError("session_not_found")
        return runtime


@lru_cache
def get_pipeline_runtime_service() -> PipelineRuntimeService:
    return PipelineRuntimeService()
