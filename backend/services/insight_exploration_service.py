from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Awaitable, Callable

from core.settings import get_settings
from core.llm_client import chat, is_configured
from models.schemas import KnowledgeGraphRetrieveRequest
from repositories.research_history_repository import (
    ResearchHistoryRepository,
    get_research_history_repository,
)
from services.insight_agent_contracts import (
    AgentMemoryWriteRecord,
    AgentProfile,
    AgentTask,
    AgentTaskResult,
    AgentToolCallRecord,
    InsightOrchestrationJournal,
    SubAgentRequest,
    default_memory_scopes,
)
from services.insight_orchestrator_service import (
    InsightOrchestratorService,
    OrchestratorLimits,
)
from services.insight_worker_pool import InsightWorkerPool, WorkerPoolConfig
from services.insight_memory_service import InsightMemoryService
from services.insight_tool_gateway import InsightToolGateway
from services.graphrag_service import GraphRAGService, get_graphrag_service

try:  # pragma: no cover - optional runtime dependency in some envs
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    _REPORTLAB_AVAILABLE = True
except Exception:  # noqa: BLE001
    A4 = None  # type: ignore[assignment]
    pdfmetrics = None  # type: ignore[assignment]
    UnicodeCIDFont = None  # type: ignore[assignment]
    canvas = None  # type: ignore[assignment]
    _REPORTLAB_AVAILABLE = False

StreamCallback = Callable[[dict[str, Any]], Awaitable[None]]

_DEFAULT_AGENT_COUNT = 4
_DEFAULT_EXPLORATION_DEPTH = 2
_DEFAULT_AGENT_MODE = "orchestrated"
_MIN_AGENT_COUNT = 2
_MAX_AGENT_COUNT = 8
_MIN_EXPLORATION_DEPTH = 1
_MAX_EXPLORATION_DEPTH = 5
_MAX_EXPANSION_PAPERS = 24
_MAX_EXPANSION_QUERIES_PER_ROUND = 2
_ALLOWED_AGENT_MODES = {"legacy", "orchestrated"}


@dataclass(frozen=True)
class _RoleSpec:
    role_id: str
    title_zh: str
    title_en: str
    focus: str


class InsightExplorationService:
    _ROLE_POOL: tuple[_RoleSpec, ...] = (
        _RoleSpec("state_analyst", "现状分析师", "State Analyst", "宏观现状与发展趋势"),
        _RoleSpec("relation_analyst", "关系分析师", "Relation Analyst", "论文关系与知识结构"),
        _RoleSpec("innovation_architect", "创新架构师", "Innovation Architect", "可行创新架构"),
        _RoleSpec("application_designer", "应用设计师", "Application Designer", "创新应用场景"),
        _RoleSpec("evidence_scout", "证据侦察员", "Evidence Scout", "增量证据检索与核对"),
        _RoleSpec("feasibility_critic", "可行性评审员", "Feasibility Critic", "实施可行性与里程碑"),
        _RoleSpec("risk_skeptic", "风险审校员", "Risk Skeptic", "风险、假设与约束"),
        _RoleSpec("synthesis_editor", "综合编辑", "Synthesis Editor", "多角色整合与表达"),
    )

    def __init__(
        self,
        *,
        graph_service: GraphRAGService | None = None,
        history_repository: ResearchHistoryRepository | None = None,
        orchestrator: InsightOrchestratorService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.worker_execution_backend = str(
            getattr(self.settings, "insight_worker_execution_backend", "subprocess") or "subprocess"
        ).strip().lower()
        if self.worker_execution_backend not in {"inprocess", "subprocess"}:
            self.worker_execution_backend = "subprocess"
        self.worker_subprocess_timeout_seconds = float(
            getattr(self.settings, "insight_worker_subprocess_timeout_seconds", 40.0) or 40.0
        )
        self.graph_service = graph_service or get_graphrag_service()
        self.history_repository = history_repository or get_research_history_repository()
        self.tool_gateway = InsightToolGateway()
        self.subprocess_worker_script = Path(__file__).resolve().with_name("insight_subprocess_worker.py")
        if orchestrator is not None:
            self.orchestrator = orchestrator
        else:
            self.orchestrator = InsightOrchestratorService(
                limits=OrchestratorLimits(
                    max_subagent_depth=max(0, int(self.settings.insight_max_subagent_depth)),
                    max_subtasks_per_round=max(1, int(self.settings.insight_max_subtasks_per_round)),
                    max_subtasks_per_parent=max(1, int(self.settings.insight_max_subtasks_per_parent)),
                    max_batch_size=max(1, min(64, int(self.settings.insight_worker_count) * 2)),
                ),
                worker_pool=InsightWorkerPool(
                    config=WorkerPoolConfig(
                        worker_count=max(1, int(self.settings.insight_worker_count)),
                    )
                ),
            )
        self.report_root = Path(__file__).resolve().parents[1] / "cache" / "reports"

    async def generate_report(
        self,
        *,
        session_id: str,
        user_id: str,
        query: str,
        input_type: str,
        papers: list[dict[str, Any]],
        graph_payload: dict[str, Any] | None,
        agent_count: int,
        exploration_depth: int,
        preferred_language: str | None = None,
        agent_mode: str | None = None,
        stream_callback: StreamCallback | None = None,
    ) -> dict[str, Any]:
        safe_session_id = str(session_id or "").strip()
        safe_user_id = str(user_id or "").strip()
        safe_query = str(query or "").strip()
        safe_input_type = str(input_type or "domain").strip().lower()
        if not safe_session_id or not safe_query:
            raise ValueError("insight_report_requires_session_and_query")

        resolved_agent_count = self._clamp_int(
            agent_count,
            default=_DEFAULT_AGENT_COUNT,
            min_value=_MIN_AGENT_COUNT,
            max_value=_MAX_AGENT_COUNT,
        )
        resolved_depth = self._clamp_int(
            exploration_depth,
            default=_DEFAULT_EXPLORATION_DEPTH,
            min_value=_MIN_EXPLORATION_DEPTH,
            max_value=_MAX_EXPLORATION_DEPTH,
        )
        resolved_mode = self._resolve_agent_mode(agent_mode)
        language = self._resolve_report_language(preferred_language, safe_query)
        active_roles = list(self._ROLE_POOL[:resolved_agent_count])
        rounds = max(1, resolved_depth * 2)

        if resolved_mode == "orchestrated":
            return await self._generate_report_orchestrated(
                session_id=safe_session_id,
                user_id=safe_user_id,
                query=safe_query,
                input_type=safe_input_type,
                normalized_papers=self._normalize_papers(papers),
                graph_payload=graph_payload if isinstance(graph_payload, dict) else {},
                agent_count=resolved_agent_count,
                exploration_depth=resolved_depth,
                language=language,
                active_roles=active_roles,
                rounds=rounds,
                stream_callback=stream_callback,
            )

        normalized_papers = self._normalize_papers(papers)
        graph_stats = self._extract_graph_stats(graph_payload or {})
        history_memory = await asyncio.to_thread(self._load_history_memory, safe_user_id)
        session_memory = {
            "hypotheses": [],
            "evidence": [],
            "decisions": [],
            "critic_notes": [],
        }
        extension_notes: list[str] = []
        extension_papers: list[dict[str, Any]] = []

        for round_index in range(1, rounds + 1):
            expansion_queries = self._build_round_expansion_queries(
                base_query=safe_query,
                round_index=round_index,
                papers=normalized_papers + extension_papers,
            )
            expansion_queries = expansion_queries[:_MAX_EXPANSION_QUERIES_PER_ROUND]
            if expansion_queries and len(extension_papers) < _MAX_EXPANSION_PAPERS:
                retrieved = await self._retrieve_extension_papers(
                    query_list=expansion_queries,
                    input_type=safe_input_type,
                    remaining=max(1, _MAX_EXPANSION_PAPERS - len(extension_papers)),
                )
                if retrieved:
                    extension_papers = self._merge_papers(extension_papers, retrieved, limit=_MAX_EXPANSION_PAPERS)
                    extension_notes.append(
                        self._format_line(
                            language,
                            zh=f"第 {round_index} 轮扩展检索：新增 {len(retrieved)} 篇候选论文（累计 {len(extension_papers)}）。",
                            en=f"Round {round_index} expansion retrieved {len(retrieved)} papers ({len(extension_papers)} total).",
                        )
                    )

            role_outputs = await self._run_role_round(
                round_index=round_index,
                roles=active_roles,
                language=language,
                query=safe_query,
                papers=normalized_papers,
                extension_papers=extension_papers,
                graph_stats=graph_stats,
                history_memory=history_memory,
                session_memory=session_memory,
            )
            session_memory["decisions"].extend(role_outputs)

        markdown = await self._compose_markdown(
            language=language,
            query=safe_query,
            input_type=safe_input_type,
            base_papers=normalized_papers,
            extension_papers=extension_papers,
            graph_stats=graph_stats,
            history_memory=history_memory,
            session_memory=session_memory,
            active_roles=active_roles,
            rounds=rounds,
            extension_notes=extension_notes,
        )

        if stream_callback is not None:
            await self._stream_markdown(
                markdown=markdown,
                callback=stream_callback,
                section="insight_markdown",
            )

        artifact = await asyncio.to_thread(
            self._persist_artifacts,
            session_id=safe_session_id,
            markdown=markdown,
            language=language,
        )
        summary = self._build_summary(
            language=language,
            extension_count=len(extension_papers),
            role_count=len(active_roles),
            rounds=rounds,
            base_papers=len(normalized_papers),
        )
        return {
            "language": language,
            "agent_mode": resolved_mode,
            "markdown": markdown,
            "summary": summary,
            "artifact": artifact,
            "memory": {
                "history": history_memory,
                "session": session_memory,
            },
            "stats": {
                "base_paper_count": len(normalized_papers),
                "extension_paper_count": len(extension_papers),
                "rounds": rounds,
                "agent_count": len(active_roles),
                "mode": resolved_mode,
                "execution_backend": "inprocess",
            },
        }

    def _resolve_agent_mode(self, agent_mode: str | None) -> str:
        candidate = str(agent_mode or "").strip().lower()
        if candidate in _ALLOWED_AGENT_MODES:
            return candidate
        configured = str(getattr(self.settings, "insight_agent_mode", _DEFAULT_AGENT_MODE) or "").strip().lower()
        if configured in _ALLOWED_AGENT_MODES:
            return configured
        return _DEFAULT_AGENT_MODE

    async def _generate_report_orchestrated(
        self,
        *,
        session_id: str,
        user_id: str,
        query: str,
        input_type: str,
        normalized_papers: list[dict[str, Any]],
        graph_payload: dict[str, Any],
        agent_count: int,
        exploration_depth: int,
        language: str,
        active_roles: list[_RoleSpec],
        rounds: int,
        stream_callback: StreamCallback | None,
    ) -> dict[str, Any]:
        streamed_chars = 0

        graph_stats = self._extract_graph_stats(graph_payload or {})
        history_memory = await asyncio.to_thread(self._load_history_memory, user_id)
        extension_notes: list[str] = []
        extension_papers: list[dict[str, Any]] = []

        profiles = self._build_agent_profiles(active_roles)
        profiles_by_id = {item.profile_id: item for item in profiles}
        role_by_profile_id = {item.role_id: role for role, item in zip(active_roles, profiles)}
        journal = InsightOrchestrationJournal(run_id=f"insight-{session_id}")
        memory_service = InsightMemoryService()
        memory_service.initialize_run(run_id=journal.run_id, history_memory=history_memory)
        session_memory = memory_service.build_session_view(run_id=journal.run_id)
        round_task_totals: list[int] = []
        round_spawn_totals: list[int] = []

        async def on_orchestrator_event(event: dict[str, Any]) -> None:
            safe_event = dict(event)
            journal.events.append(safe_event)
            if stream_callback is not None:
                await stream_callback(
                    {
                        "section": "insight_orchestrator_event",
                        "event": safe_event,
                        "chunk": "",
                        "accumulated_chars": streamed_chars,
                        "done": False,
                    }
                )

        for round_index in range(1, rounds + 1):
            expansion_queries = self._build_round_expansion_queries(
                base_query=query,
                round_index=round_index,
                papers=normalized_papers + extension_papers,
            )
            expansion_queries = expansion_queries[:_MAX_EXPANSION_QUERIES_PER_ROUND]
            if expansion_queries and len(extension_papers) < _MAX_EXPANSION_PAPERS:
                retrieved = await self._retrieve_extension_papers(
                    query_list=expansion_queries,
                    input_type=input_type,
                    remaining=max(1, _MAX_EXPANSION_PAPERS - len(extension_papers)),
                )
                if retrieved:
                    extension_papers = self._merge_papers(extension_papers, retrieved, limit=_MAX_EXPANSION_PAPERS)
                    extension_notes.append(
                        self._format_line(
                            language,
                            zh=f"第 {round_index} 轮扩展检索：新增 {len(retrieved)} 篇候选论文（累计 {len(extension_papers)}）。",
                            en=f"Round {round_index} expansion retrieved {len(retrieved)} papers ({len(extension_papers)} total).",
                        )
                    )

            base_context = {
                "graph_stats": dict(graph_stats),
                "history_memory": history_memory[:3],
                "extension_paper_count": len(extension_papers),
                "base_paper_count": len(normalized_papers),
            }
            base_tasks = self.orchestrator.plan_round_tasks(
                run_id=journal.run_id,
                round_index=round_index,
                profiles=profiles,
                query=query,
                language=language,
                input_type=input_type,
                objective=self._format_line(
                    language,
                    zh="总结领域进展并提出可执行创新方向。",
                    en="Summarize field progress and propose executable innovation paths.",
                ),
                shared_context=base_context,
            )

            round_result = await self.orchestrator.execute_round(
                round_index=round_index,
                base_tasks=base_tasks,
                profiles_by_id=profiles_by_id,
                executor=lambda task, worker_id: self._execute_orchestrated_task(
                    task=task,
                    worker_id=worker_id,
                    profiles_by_id=profiles_by_id,
                    role_by_profile_id=role_by_profile_id,
                    language=language,
                    query=query,
                    papers=normalized_papers,
                    extension_papers=extension_papers,
                    graph_stats=graph_stats,
                    history_memory=history_memory,
                    memory_service=memory_service,
                ),
                event_callback=on_orchestrator_event,
            )
            journal.rounds.append(round_result)
            round_task_totals.append(int(round_result.total_task_count))
            round_spawn_totals.append(int(round_result.spawned_task_count))

            role_outputs: list[str] = []
            for result in round_result.results:
                result_worker_id = str((result.extra or {}).get("worker_id") or "").strip() or "main"
                memory_service.write_many(
                    run_id=journal.run_id,
                    records=list(result.memory_writes or []),
                    worker_id=result_worker_id,
                )
                self._apply_memory_writes(session_memory=session_memory, result=result)
                output = str(result.output or "").strip()
                if output:
                    role_outputs.append(output)
            session_memory = memory_service.build_session_view(run_id=journal.run_id)

        markdown = await self._compose_markdown(
            language=language,
            query=query,
            input_type=input_type,
            base_papers=normalized_papers,
            extension_papers=extension_papers,
            graph_stats=graph_stats,
            history_memory=history_memory,
            session_memory=session_memory,
            active_roles=active_roles,
            rounds=rounds,
            extension_notes=extension_notes,
        )
        if stream_callback is not None:
            await self._stream_markdown(
                markdown=markdown,
                callback=stream_callback,
                section="insight_markdown",
            )

        artifact = await asyncio.to_thread(
            self._persist_artifacts,
            session_id=session_id,
            markdown=markdown,
            language=language,
        )
        summary = self._build_summary(
            language=language,
            extension_count=len(extension_papers),
            role_count=len(active_roles),
            rounds=rounds,
            base_papers=len(normalized_papers),
        )
        return {
            "language": language,
            "agent_mode": "orchestrated",
            "markdown": markdown,
            "summary": summary,
            "artifact": artifact,
            "memory": {
                "history": history_memory,
                "session": session_memory,
                "scoped": memory_service.snapshot(run_id=journal.run_id),
            },
            "stats": {
                "base_paper_count": len(normalized_papers),
                "extension_paper_count": len(extension_papers),
                "rounds": rounds,
                "agent_count": len(active_roles),
                "mode": "orchestrated",
                "execution_backend": self.worker_execution_backend,
                "orchestration_round_task_counts": round_task_totals,
                "orchestration_round_spawn_counts": round_spawn_totals,
                "orchestration_event_count": len(journal.events),
            },
        }

    def _build_agent_profiles(self, active_roles: list[_RoleSpec]) -> list[AgentProfile]:
        profiles: list[AgentProfile] = []
        for role in active_roles:
            profiles.append(
                AgentProfile(
                    profile_id=role.role_id,
                    role_id=role.role_id,
                    display_name_zh=role.title_zh,
                    display_name_en=role.title_en,
                    skills=self._resolve_role_skills(role.role_id),
                    allowed_tools=self._resolve_role_tools(role.role_id),
                    memory_scopes=default_memory_scopes(include_history=True),
                    max_subagents=max(1, int(self.orchestrator.limits.max_subtasks_per_parent)),
                )
            )
        return profiles

    @staticmethod
    def _resolve_role_skills(role_id: str) -> tuple[str, ...]:
        mapping: dict[str, tuple[str, ...]] = {
            "state_analyst": ("trend_analysis", "evidence_synthesis"),
            "relation_analyst": ("citation_graph_reasoning", "cluster_mapping"),
            "innovation_architect": ("architecture_design", "constraint_tradeoff"),
            "application_designer": ("scenario_design", "value_hypothesis"),
            "evidence_scout": ("expansion_retrieval", "evidence_validation"),
            "feasibility_critic": ("execution_planning", "milestone_estimation"),
            "risk_skeptic": ("risk_modeling", "assumption_audit"),
            "synthesis_editor": ("multi_view_synthesis", "report_composition"),
        }
        return mapping.get(str(role_id or "").strip(), ("general_analysis",))

    @staticmethod
    def _resolve_role_tools(role_id: str) -> tuple[str, ...]:
        mapping: dict[str, tuple[str, ...]] = {
            "state_analyst": ("graph_stats", "history_memory", "llm"),
            "relation_analyst": ("graph_stats", "paper_catalog", "llm"),
            "innovation_architect": ("paper_catalog", "history_memory", "llm"),
            "application_designer": ("paper_catalog", "llm"),
            "evidence_scout": ("expansion_retrieval", "paper_catalog", "llm"),
            "feasibility_critic": ("history_memory", "paper_catalog", "llm"),
            "risk_skeptic": ("history_memory", "paper_catalog", "llm"),
            "synthesis_editor": ("paper_catalog", "graph_stats", "llm"),
        }
        return mapping.get(str(role_id or "").strip(), ("llm",))

    @staticmethod
    def _resolve_role_report_focus(*, role_id: str, language: str) -> str:
        safe_language = str(language or "").strip().lower()
        safe_role_id = str(role_id or "").strip()
        mapping_zh: dict[str, str] = {
            "state_analyst": "鼻祖论文起源、早期方法与首批落地应用",
            "relation_analyst": "鼻祖论文之后的技术分支与延续链条",
            "innovation_architect": "尚未被充分挖掘的创新方向与架构机会",
            "application_designer": "当前可落地场景、部署形态与应用价值",
            "evidence_scout": "关键论文证据与可核验引用线索",
            "feasibility_critic": "应用落地约束、实施条件与可行路径",
            "risk_skeptic": "延续路线中的核心风险、假设与反例",
            "synthesis_editor": "形成完整叙事：起源-延续-应用-创新空白",
        }
        mapping_en: dict[str, str] = {
            "state_analyst": "origin paper, early method rationale, and first deployments",
            "relation_analyst": "continuation chain and technical branches after the seminal work",
            "innovation_architect": "under-explored innovation opportunities and architecture ideas",
            "application_designer": "current deployment scenarios and practical value capture",
            "evidence_scout": "verifiable paper evidence and citation-quality traceability",
            "feasibility_critic": "constraints, requirements, and executable implementation paths",
            "risk_skeptic": "core risks, assumptions, and counter-evidence in continuation tracks",
            "synthesis_editor": "a coherent narrative from origin to continuation, deployment, and open gaps",
        }
        if safe_language == "zh":
            return mapping_zh.get(safe_role_id, "基于证据补齐该方向的核心研究脉络")
        return mapping_en.get(safe_role_id, "complete the evidence-backed research storyline")

    async def _execute_orchestrated_task(
        self,
        *,
        task: AgentTask,
        worker_id: str,
        profiles_by_id: dict[str, AgentProfile],
        role_by_profile_id: dict[str, _RoleSpec],
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        memory_service: InsightMemoryService,
    ) -> AgentTaskResult:
        role = role_by_profile_id.get(task.profile_id)
        profile = profiles_by_id.get(task.profile_id)
        if profile is None:
            return AgentTaskResult(
                task_id=task.task_id,
                profile_id=task.profile_id,
                role_id=task.role_id,
                status="failed",
                output="",
                extra={"error": "unknown_profile_registration"},
            )
        if role is None:
            return AgentTaskResult(
                task_id=task.task_id,
                profile_id=task.profile_id,
                role_id=task.role_id,
                status="failed",
                output="",
                extra={"error": "unknown_profile"},
            )

        tool_context = {
            "graph_stats": graph_stats,
            "papers": papers + extension_papers,
            "history_memory": history_memory,
            "extension_papers": extension_papers,
            "llm_enabled": is_configured(),
            "query": query,
            "input_type": task.input_type,
            "worker_id": worker_id,
            "depth": task.depth,
            "context": dict(task.context or {}),
        }
        tool_calls: list[AgentToolCallRecord] = []
        for tool_name in profile.allowed_tools:
            payload, record = self.tool_gateway.invoke(
                task_id=task.task_id,
                profile=profile,
                tool_name=tool_name,
                context=tool_context,
            )
            tool_calls.append(record)
            if payload is None:
                continue
            tool_context[f"tool::{tool_name}"] = payload

        llm_enabled = any(
            record.tool_name == "llm" and record.status == "ok"
            for record in tool_calls
        )
        session_memory = memory_service.clone_session_view(run_id=task.run_id)
        agent_private = memory_service.read_agent(
            run_id=task.run_id,
            profile_id=task.profile_id,
            key="private_notes",
            limit=4,
            worker_id=worker_id,
        )
        effective_objective = str(task.objective or "").strip()
        if agent_private:
            effective_objective = (
                f"{effective_objective}\n"
                f"Private memory: {agent_private}"
            ).strip()

        execution_backend = "inprocess"
        try:
            if self.worker_execution_backend == "subprocess":
                output = await self._run_single_role_in_subprocess(
                    round_index=task.round_index,
                    role=role,
                    language=language,
                    query=query,
                    papers=papers,
                    extension_papers=extension_papers,
                    graph_stats=graph_stats,
                    history_memory=history_memory,
                    session_memory=session_memory,
                    objective=effective_objective,
                    allow_llm=llm_enabled,
                )
                execution_backend = "subprocess"
            else:
                output = await self._run_single_role(
                    round_index=task.round_index,
                    role=role,
                    language=language,
                    query=query,
                    papers=papers,
                    extension_papers=extension_papers,
                    graph_stats=graph_stats,
                    history_memory=history_memory,
                    session_memory=session_memory,
                    objective=effective_objective,
                    allow_llm=llm_enabled,
                )
        except Exception as exc:  # noqa: BLE001
            if self.worker_execution_backend == "subprocess":
                try:
                    output = await self._run_single_role(
                        round_index=task.round_index,
                        role=role,
                        language=language,
                        query=query,
                        papers=papers,
                        extension_papers=extension_papers,
                        graph_stats=graph_stats,
                        history_memory=history_memory,
                        session_memory=session_memory,
                        objective=effective_objective,
                        allow_llm=llm_enabled,
                    )
                    execution_backend = "inprocess_fallback"
                except Exception:  # noqa: BLE001
                    return AgentTaskResult(
                        task_id=task.task_id,
                        profile_id=task.profile_id,
                        role_id=task.role_id,
                        status="failed",
                        output="",
                        tool_calls=tool_calls,
                        extra={"error": str(exc)},
                    )
            else:
                return AgentTaskResult(
                    task_id=task.task_id,
                    profile_id=task.profile_id,
                    role_id=task.role_id,
                    status="failed",
                    output="",
                    tool_calls=tool_calls,
                    extra={"error": str(exc)},
                )

        memory_writes = self._build_memory_writes_for_output(
            task=task,
            role=role,
            output=output,
        )
        subagent_requests = self._build_subagent_requests(
            task=task,
            role=role,
            output=output,
            role_by_profile_id=role_by_profile_id,
        )
        return AgentTaskResult(
            task_id=task.task_id,
            profile_id=task.profile_id,
            role_id=task.role_id,
            status="completed",
            output=output,
            tool_calls=tool_calls,
            memory_writes=memory_writes,
            subagent_requests=subagent_requests,
            extra={
                "role_id": role.role_id,
                "depth": task.depth,
                "parent_task_id": task.parent_task_id,
                "worker_id": worker_id,
                "execution_backend": execution_backend,
            },
        )

    def _build_memory_writes_for_output(
        self,
        *,
        task: AgentTask,
        role: _RoleSpec,
        output: str,
    ) -> list[AgentMemoryWriteRecord]:
        safe_output = str(output or "").strip()
        if not safe_output:
            return []
        writes: list[AgentMemoryWriteRecord] = [
            AgentMemoryWriteRecord(
                task_id=task.task_id,
                profile_id=task.profile_id,
                scope="session_shared",
                key="evidence",
                value=safe_output[:200],
            ),
            AgentMemoryWriteRecord(
                task_id=task.task_id,
                profile_id=task.profile_id,
                scope="session_shared",
                key="decisions",
                value=safe_output,
            ),
            AgentMemoryWriteRecord(
                task_id=task.task_id,
                profile_id=task.profile_id,
                scope="agent_private",
                key="private_notes",
                value=safe_output[:300],
            ),
        ]
        if role.role_id in {"innovation_architect", "application_designer"}:
            writes.append(
                AgentMemoryWriteRecord(
                    task_id=task.task_id,
                    profile_id=task.profile_id,
                    scope="session_shared",
                    key="hypotheses",
                    value=safe_output,
                )
            )
        if role.role_id in {"risk_skeptic", "feasibility_critic"}:
            writes.append(
                AgentMemoryWriteRecord(
                    task_id=task.task_id,
                    profile_id=task.profile_id,
                    scope="session_shared",
                    key="critic_notes",
                    value=safe_output,
                )
            )
        return writes

    def _build_subagent_requests(
        self,
        *,
        task: AgentTask,
        role: _RoleSpec,
        output: str,
        role_by_profile_id: dict[str, _RoleSpec],
    ) -> list[SubAgentRequest]:
        if task.depth >= int(self.orchestrator.limits.max_subagent_depth):
            return []
        focus = str(output or "").strip()[:180]
        if not focus:
            return []
        role_targets: dict[str, str] = {
            "innovation_architect": "evidence_scout",
            "application_designer": "evidence_scout",
            "relation_analyst": "risk_skeptic",
            "state_analyst": "feasibility_critic",
            "feasibility_critic": "synthesis_editor",
        }
        target_role_id = role_targets.get(role.role_id, "")
        if not target_role_id:
            return []
        target_profile_id = next(
            (profile_id for profile_id, spec in role_by_profile_id.items() if spec.role_id == target_role_id),
            "",
        )
        if not target_profile_id:
            return []
        return [
            SubAgentRequest(
                objective=self._format_line(
                    task.language,
                    zh=f"围绕以下线索做补充分析并给出可执行建议：{focus}",
                    en=f"Expand this clue with executable recommendations: {focus}",
                ),
                profile_id=target_profile_id,
                role_id=target_role_id,
                context_patch={
                    "parent_role_id": role.role_id,
                    "parent_task_id": task.task_id,
                },
            )
        ]

    @staticmethod
    def _apply_memory_writes(
        *,
        session_memory: dict[str, list[str]],
        result: AgentTaskResult,
    ) -> None:
        for write in list(result.memory_writes or []):
            if write.scope != "session_shared":
                continue
            key = str(write.key or "").strip()
            if key not in session_memory:
                continue
            value = str(write.value or "").strip()
            if not value:
                continue
            session_memory[key].append(value)

    @staticmethod
    def _clamp_int(value: object, *, default: int, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _resolve_report_language(preferred_language: str | None, query: str) -> str:
        safe_preferred = str(preferred_language or "").strip().lower()
        if safe_preferred in {"zh", "en"}:
            return safe_preferred
        return InsightExplorationService._detect_language(query)

    @staticmethod
    def _detect_language(text: str) -> str:
        return "zh" if re.search(r"[\u4e00-\u9fff]", str(text or "")) else "en"

    @staticmethod
    def _normalize_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in papers or []:
            if not isinstance(item, dict):
                continue
            paper_id = str(item.get("paper_id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not paper_id and not title:
                continue
            items.append(
                {
                    "paper_id": paper_id,
                    "title": title or paper_id,
                    "year": InsightExplorationService._safe_int(item.get("year"), 0),
                    "citation_count": InsightExplorationService._safe_int(item.get("citation_count"), 0),
                    "venue": str(item.get("venue") or "").strip(),
                    "abstract": str(item.get("abstract") or "").strip(),
                    "authors": [
                        str(author).strip()
                        for author in (item.get("authors") or [])
                        if str(author).strip()
                    ],
                }
            )
        return items

    @staticmethod
    def _extract_graph_stats(graph_payload: dict[str, Any]) -> dict[str, int]:
        nodes = list(graph_payload.get("nodes") or [])
        edges = list(graph_payload.get("edges") or [])
        paper_nodes = [
            node
            for node in nodes
            if str(node.get("type") or node.get("kind") or "").strip().lower() == "paper"
        ]
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "paper_node_count": len(paper_nodes),
        }

    def _load_history_memory(self, user_id: str) -> list[str]:
        safe_user_id = str(user_id or "").strip()
        if not safe_user_id:
            return []
        try:
            rows, _ = self.history_repository.list_graph_records(
                user_id=safe_user_id,
                page=1,
                page_size=5,
            )
        except Exception:  # noqa: BLE001
            return []

        memory: list[str] = []
        for row in rows:
            history_id = str(row.get("history_id") or "").strip()
            if not history_id:
                continue
            try:
                detail = self.history_repository.get_graph_record(
                    user_id=safe_user_id,
                    history_id=history_id,
                )
            except Exception:  # noqa: BLE001
                detail = None
            if not isinstance(detail, dict):
                continue
            graph_payload = detail.get("graph_payload")
            if not isinstance(graph_payload, dict):
                continue
            pipeline = graph_payload.get("pipeline")
            if not isinstance(pipeline, dict):
                continue
            insight = pipeline.get("insight")
            if not isinstance(insight, dict):
                continue
            summary = str(insight.get("summary") or "").strip()
            if summary:
                memory.append(summary)
            if len(memory) >= 3:
                break
        return memory

    def _build_round_expansion_queries(
        self,
        *,
        base_query: str,
        round_index: int,
        papers: list[dict[str, Any]],
    ) -> list[str]:
        keywords: list[str] = [base_query]
        for item in papers[: min(12, len(papers))]:
            title = str(item.get("title") or "").strip()
            if title:
                keywords.extend(self._tokenize_title(title))
        deduped: list[str] = []
        seen: set[str] = set()
        for token in keywords:
            safe = str(token or "").strip()
            if not safe:
                continue
            key = safe.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(safe)
            if len(deduped) >= 8:
                break
        if not deduped:
            deduped = [base_query]

        pivot = deduped[(round_index - 1) % len(deduped)]
        return [
            f"{base_query} {pivot} innovation",
            f"{base_query} {pivot} application",
        ]

    @staticmethod
    def _tokenize_title(title: str) -> list[str]:
        tokens = re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", str(title or "").strip())
        cleaned = [token for token in tokens if len(token) >= 4 or re.search(r"[\u4e00-\u9fff]", token)]
        return cleaned[:3]

    async def _retrieve_extension_papers(
        self,
        *,
        query_list: list[str],
        input_type: str,
        remaining: int,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        if remaining <= 0:
            return collected
        for query in query_list:
            safe_query = str(query or "").strip()
            if not safe_query:
                continue
            request = KnowledgeGraphRetrieveRequest(
                query=safe_query,
                max_papers=max(3, min(8, remaining)),
                input_type="domain" if input_type == "domain" else "domain",
                quick_mode=True,
                paper_range_years=None,
            )
            try:
                payload = await asyncio.to_thread(self.graph_service.retrieve_papers, request)
            except Exception:  # noqa: BLE001
                continue
            papers = [paper.model_dump(mode="json") for paper in payload.papers]
            if not papers:
                continue
            collected = self._merge_papers(collected, papers, limit=remaining)
            if len(collected) >= remaining:
                break
        return collected

    async def _run_role_round(
        self,
        *,
        round_index: int,
        roles: list[_RoleSpec],
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
    ) -> list[str]:
        outputs: list[str] = []
        for role in roles:
            content = await self._run_single_role(
                round_index=round_index,
                role=role,
                language=language,
                query=query,
                papers=papers,
                extension_papers=extension_papers,
                graph_stats=graph_stats,
                history_memory=history_memory,
                session_memory=session_memory,
            )
            outputs.append(content)
            if role.role_id in {"risk_skeptic", "feasibility_critic"}:
                session_memory["critic_notes"].append(content)
            if role.role_id in {"innovation_architect", "application_designer"}:
                session_memory["hypotheses"].append(content)
            session_memory["evidence"].append(content[:160])
        return outputs

    async def _run_single_role_in_subprocess(
        self,
        *,
        round_index: int,
        role: _RoleSpec,
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
        objective: str | None = None,
        allow_llm: bool = True,
    ) -> str:
        if not self.subprocess_worker_script.exists():
            raise RuntimeError("insight_subprocess_worker_not_found")

        payload = {
            "round_index": int(round_index),
            "language": str(language or "en"),
            "query": str(query or ""),
            "papers": [dict(item) for item in papers if isinstance(item, dict)],
            "extension_papers": [dict(item) for item in extension_papers if isinstance(item, dict)],
            "graph_stats": dict(graph_stats or {}),
            "history_memory": [str(item) for item in history_memory if str(item).strip()],
            "session_memory": {
                str(key): [str(line) for line in (lines or []) if str(line).strip()]
                for key, lines in dict(session_memory or {}).items()
                if str(key).strip()
            },
            "objective": str(objective or ""),
            "allow_llm": bool(allow_llm),
            "role": {
                "role_id": role.role_id,
                "title_zh": role.title_zh,
                "title_en": role.title_en,
                "focus": role.focus,
            },
        }
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.subprocess_worker_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
            timeout=max(5.0, float(self.worker_subprocess_timeout_seconds)),
        )
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"insight_worker_process_failed:{process.returncode}:{detail[:300]}")

        raw_output = stdout.decode("utf-8", errors="ignore").strip()
        if not raw_output:
            raise RuntimeError("insight_worker_process_empty_output")
        parsed = json.loads(raw_output)
        if not isinstance(parsed, dict):
            raise RuntimeError("insight_worker_process_invalid_payload")
        content = str(parsed.get("output") or "").strip()
        if not content:
            raise RuntimeError("insight_worker_process_no_content")
        return content

    async def _run_single_role(
        self,
        *,
        round_index: int,
        role: _RoleSpec,
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
        objective: str | None = None,
        allow_llm: bool = True,
    ) -> str:
        if (not allow_llm) or (not is_configured()):
            return self._fallback_role_output(
                round_index=round_index,
                role=role,
                language=language,
                query=query,
                papers=papers,
                extension_papers=extension_papers,
                graph_stats=graph_stats,
            )

        prompt = self._build_role_prompt(
            round_index=round_index,
            role=role,
            language=language,
            query=query,
            papers=papers,
            extension_papers=extension_papers,
            graph_stats=graph_stats,
            history_memory=history_memory,
            session_memory=session_memory,
            objective=objective,
        )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    chat,
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are a specialized research analyst. "
                                "Return one deep paragraph with evidence-backed and actionable insights. "
                                "Do not describe workflow or agent collaboration process."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    temperature=0.25,
                    timeout=20,
                ),
                timeout=24,
            )
            content = str(response.choices[0].message.content or "").strip()
            if content:
                return content
        except Exception:  # noqa: BLE001
            pass
        return self._fallback_role_output(
            round_index=round_index,
            role=role,
            language=language,
            query=query,
            papers=papers,
            extension_papers=extension_papers,
            graph_stats=graph_stats,
        )

    def _build_role_prompt(
        self,
        *,
        round_index: int,
        role: _RoleSpec,
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
        objective: str | None = None,
    ) -> str:
        top_papers = self._top_papers_for_prompt(papers + extension_papers, limit=6)
        role_name = role.title_zh if language == "zh" else role.title_en
        role_focus = self._resolve_role_report_focus(role_id=role.role_id, language=language)
        context = {
            "query": query,
            "round": round_index,
            "role": role_name,
            "focus": role.focus,
            "report_focus": role_focus,
            "objective": str(objective or "").strip(),
            "graph_stats": graph_stats,
            "top_papers": top_papers,
            "history_memory": history_memory[:2],
            "session_hypotheses": (session_memory.get("hypotheses") or [])[-2:],
            "session_critic_notes": (session_memory.get("critic_notes") or [])[-2:],
        }
        if language == "zh":
            return (
                "你是科研分析写作助手。请基于上下文输出一段中文深度分析（220-420字）。"
                f"本段重点：{role_focus}。"
                "内容必须包含：证据链（引用论文标题/年份）、关键判断、可执行建议。"
                "禁止描述工作流、Agent、子代理、协商轮次、工具调用过程。"
                "上下文："
                f"{context}"
            )
        return (
            "You are a research writing analyst. Produce one deep English paragraph (150-260 words). "
            f"Primary focus: {role_focus}. "
            "The paragraph must include evidence links (paper title/year), key judgments, and executable recommendations. "
            "Do not describe workflow, agents, rounds, or tool invocation process. "
            f"Context: {context}"
        )

    def _fallback_role_output(
        self,
        *,
        round_index: int,
        role: _RoleSpec,
        language: str,
        query: str,
        papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
    ) -> str:
        total_papers = len(papers) + len(extension_papers)
        if language == "zh":
            return (
                f"围绕“{query}”的证据中，当前样本共 {total_papers} 篇论文，"
                f"图谱节点 {graph_stats['node_count']}、关系 {graph_stats['edge_count']}。"
                f"建议围绕“{self._resolve_role_report_focus(role_id=role.role_id, language='zh')}”"
                "补齐“起源论文-延续工作-应用落地-创新空白”的连续证据链，并优先规划可验证的小规模试点。"
            )
        return (
            f"For '{query}', the evidence pool currently contains {total_papers} papers "
            f"with {graph_stats['node_count']} graph nodes and {graph_stats['edge_count']} relations. "
            f"Prioritize '{self._resolve_role_report_focus(role_id=role.role_id, language='en')}' "
            "and build a continuous evidence chain from origin paper to continuation work, deployments, and open innovation gaps."
        )

    async def _compose_markdown(
        self,
        *,
        language: str,
        query: str,
        input_type: str,
        base_papers: list[dict[str, Any]],
        extension_papers: list[dict[str, Any]],
        graph_stats: dict[str, int],
        history_memory: list[str],
        session_memory: dict[str, list[str]],
        active_roles: list[_RoleSpec],
        rounds: int,
        extension_notes: list[str],
    ) -> str:
        del input_type, active_roles, rounds
        safe_language = "zh" if language == "zh" else "en"
        all_papers = self._merge_papers(
            base_papers,
            extension_papers,
            limit=max(1, len(base_papers) + len(extension_papers)),
        )
        papers_sorted_by_year = sorted(
            [item for item in all_papers if self._safe_int(item.get("year"), 0) > 0],
            key=lambda item: (
                self._safe_int(item.get("year"), 0),
                -self._safe_int(item.get("citation_count"), 0),
                str(item.get("title") or "").lower(),
            ),
        )
        papers_sorted_by_citation = sorted(
            all_papers,
            key=lambda item: (
                self._safe_int(item.get("citation_count"), 0),
                self._safe_int(item.get("year"), 0),
            ),
            reverse=True,
        )

        if papers_sorted_by_year:
            founder_candidates = papers_sorted_by_year[:3]
        else:
            founder_candidates = papers_sorted_by_citation[:3]
        founder_primary = founder_candidates[0] if founder_candidates else None

        decisions = self._dedupe_report_lines(session_memory.get("decisions") or [], limit=36, language=safe_language)
        hypotheses = self._dedupe_report_lines(session_memory.get("hypotheses") or [], limit=18, language=safe_language)
        critic_notes = self._dedupe_report_lines(session_memory.get("critic_notes") or [], limit=18, language=safe_language)
        history_notes = self._dedupe_report_lines(history_memory or [], limit=8, language=safe_language)
        del extension_notes
        narrative_pool = self._dedupe_report_lines(
            decisions + hypotheses + critic_notes + history_notes,
            limit=42,
            language=safe_language,
        )

        founder_notes = narrative_pool[:10]
        extension_notes_section = narrative_pool[10:22]
        application_notes = narrative_pool[22:32]
        innovation_notes = hypotheses[:10] + critic_notes[:6] + narrative_pool[32:40]
        application_clusters = self._infer_application_clusters(all_papers, language=safe_language)
        references = papers_sorted_by_citation[:40]

        if safe_language == "zh":
            sections = [
                "# 探索与洞察报告",
                "",
                "## 1. 该领域/论文的鼻祖论文、由来与最初成果落地",
            ]
            if founder_primary is not None:
                founder_title = str(founder_primary.get("title") or "未知标题").strip()
                founder_year = self._safe_int(founder_primary.get("year"), 0)
                founder_citations = self._safe_int(founder_primary.get("citation_count"), 0)
                founder_venue = str(founder_primary.get("venue") or "Unknown").strip() or "Unknown"
                sections.append(
                    (
                        f"基于当前检索样本（共 {len(all_papers)} 篇论文），最早且影响力突出的候选鼻祖论文为"
                        f"《{founder_title}》（{founder_year or '年份未知'}，引用 {founder_citations}，"
                        f"发表渠道 {founder_venue}）。以下论述严格以当前样本证据为边界，不做超样本断言。"
                    )
                )
                abstract_summary = self._summarize_abstract_text(
                    founder_primary.get("abstract"),
                    max_chars=320,
                )
                if abstract_summary:
                    sections.append(
                        f"从论文摘要可提炼的起点贡献是：{abstract_summary}"
                    )
            else:
                sections.append(
                    "当前检索样本不足以唯一锁定单一鼻祖论文，因此以下采用“最早年份 + 引用影响力”的联合标准进行候选判断。"
                )
            if founder_candidates:
                sections.append("鼻祖候选证据：")
                for item in founder_candidates:
                    sections.append(
                        f"- {self._format_paper_reference_line(item, language='zh')}"
                    )
            if founder_notes:
                sections.append("由来路径与早期落地线索：")
                for note in founder_notes:
                    sections.append(f"- {note}")
            else:
                sections.extend(
                    [
                        "- 起源阶段通常由“核心问题定义 + 可复现基线”共同形成。",
                        "- 首批落地往往出现在可测量收益明确、试点成本较低的场景。",
                        "- 从早期论文到应用验证之间，关键瓶颈通常是数据、评估与工程可靠性。",
                    ]
                )

            sections.extend(
                [
                    "",
                    "## 2. 基于鼻祖论文的扩展与延续工作（思路细节）",
                    "基于已检索论文构造的延续时间线：",
                ]
            )
            for item in papers_sorted_by_year[:16]:
                sections.append(f"- {self._format_paper_reference_line(item, language='zh')}")
            if extension_notes_section:
                sections.append("延续工作中的关键扩展思路：")
                for note in extension_notes_section[:14]:
                    sections.append(f"- {note}")
            else:
                sections.extend(
                    [
                        "- 典型延续路线包括：模型能力增强、任务迁移、数据效率优化和部署成本压缩。",
                        "- 关键细节通常体现在训练目标调整、结构约束设计和评测协议标准化。",
                        "- 延续工作是否成立，核心取决于“效果提升是否稳健、代价是否可接受、场景是否可迁移”。",
                    ]
                )

            sections.extend(
                [
                    "",
                    "## 3. 当前应用与落地（论文证据与场景）",
                    (
                        f"当前样本显示：该方向已有明确应用趋势，证据覆盖 {len(all_papers)} 篇论文，"
                        f"图谱规模为节点 {graph_stats['node_count']}、关系 {graph_stats['edge_count']}。"
                    ),
                ]
            )
            if application_clusters:
                for cluster in application_clusters[:8]:
                    scenario_name = str(cluster.get("name") or "通用场景")
                    evidence_lines = cluster.get("evidence") if isinstance(cluster.get("evidence"), list) else []
                    sections.append(f"- 场景：{scenario_name}")
                    for line in evidence_lines[:4]:
                        sections.append(f"  证据：{line}")
            if application_notes:
                sections.append("应用落地补充观察：")
                for note in application_notes[:10]:
                    sections.append(f"- {note}")
            else:
                sections.extend(
                    [
                        "- 当前落地多呈现“先局部流程替代，再逐步扩展系统边界”的推进路径。",
                        "- 高价值场景通常优先关注可量化 KPI，如准确率、时延、单位成本与可靠性。",
                        "- 论文中的可复现证据与产业部署中的长期稳定性仍存在显著鸿沟，需持续验证。",
                    ]
                )

            sections.extend(
                [
                    "",
                    "## 4. 尚未被充分挖掘的创新点（可行性发散）",
                ]
            )
            if innovation_notes:
                for note in innovation_notes[:16]:
                    sections.append(f"- {note}")
            else:
                sections.extend(
                    [
                        "- 创新点 A：跨场景迁移的统一中间表示，降低每个新场景的重新训练成本。",
                        "- 创新点 B：结合因果约束的评估框架，提升在分布偏移场景下的稳定性。",
                        "- 创新点 C：以低资源部署为目标的轻量化架构，扩大真实业务可用范围。",
                        "- 创新点 D：将知识图谱结构先验与生成模型结合，提升复杂关系推理可靠性。",
                    ]
                )

            sections.extend(
                [
                    "",
                    "## 5. 总结",
                    (
                        f"围绕“{query}”，当前证据显示该方向已经形成“起源论文 -> 连续扩展 -> 多场景落地”的主线，"
                        "但在可复现性、跨场景稳健性和规模化部署成本方面仍有明显改进空间。"
                    ),
                    "- 结论 1：鼻祖论文提供了问题定义与方法起点，后续工作主要沿性能、效率与适配性三条线并行演化。",
                    "- 结论 2：应用落地已发生，但高质量工程化仍依赖严格评估与持续迭代。",
                    "- 结论 3：下一阶段创新价值主要来自“架构整合 + 评估升级 + 低成本部署”三者协同。",
                ]
            )

            sections.extend(
                [
                    "",
                    "## 6. 引用论文情况（如实列出）",
                    (
                        f"以下为本次报告使用的论文样本清单（按引用量降序，样本内共 {len(all_papers)} 篇，"
                        f"此处展示 {len(references)} 篇）："
                    ),
                ]
            )
            for index, item in enumerate(references, start=1):
                sections.append(f"{index}. {self._format_paper_reference_line(item, language='zh')}")
            if not references:
                sections.append("- 当前样本中无可引用论文条目。")
            return "\n".join(sections).strip() + "\n"

        sections = [
            "# Exploration Insight Report",
            "",
            "## 1. Seminal Paper, Origin Path, and First Deployments",
        ]
        if founder_primary is not None:
            founder_title = str(founder_primary.get("title") or "Unknown title").strip()
            founder_year = self._safe_int(founder_primary.get("year"), 0)
            founder_citations = self._safe_int(founder_primary.get("citation_count"), 0)
            founder_venue = str(founder_primary.get("venue") or "Unknown").strip() or "Unknown"
            sections.append(
                (
                    f"Based on the current evidence pool ({len(all_papers)} papers), the leading seminal-paper candidate is "
                    f"'{founder_title}' ({founder_year or 'year unknown'}, citations {founder_citations}, venue {founder_venue}). "
                    "All conclusions below stay within the retrieved evidence scope."
                )
            )
            abstract_summary = self._summarize_abstract_text(
                founder_primary.get("abstract"),
                max_chars=420,
            )
            if abstract_summary:
                sections.append(f"Core contribution signal from the abstract: {abstract_summary}")
        else:
            sections.append(
                "The current retrieval sample is insufficient to lock a single seminal paper, so candidates are ranked by earliest year plus citation impact."
            )
        if founder_candidates:
            sections.append("Seminal-paper candidates:")
            for item in founder_candidates:
                sections.append(f"- {self._format_paper_reference_line(item, language='en')}")
        if founder_notes:
            sections.append("Origin and early adoption signals:")
            for note in founder_notes:
                sections.append(f"- {note}")

        sections.extend(
            [
                "",
                "## 2. Continuation Chain and Extension Details from the Seminal Work",
                "Timeline of continuation evidence in retrieved papers:",
            ]
        )
        for item in papers_sorted_by_year[:16]:
            sections.append(f"- {self._format_paper_reference_line(item, language='en')}")
        if extension_notes_section:
            sections.append("Detailed continuation patterns:")
            for note in extension_notes_section[:14]:
                sections.append(f"- {note}")

        sections.extend(
            [
                "",
                "## 3. Current Applications and Deployment Status (Papers + Scenarios)",
                (
                    f"Current evidence indicates active deployment tracks across {len(all_papers)} papers, "
                    f"with graph scale {graph_stats['node_count']} nodes and {graph_stats['edge_count']} relations."
                ),
            ]
        )
        if application_clusters:
            for cluster in application_clusters[:8]:
                scenario_name = str(cluster.get("name") or "General scenario")
                evidence_lines = cluster.get("evidence") if isinstance(cluster.get("evidence"), list) else []
                sections.append(f"- Scenario: {scenario_name}")
                for line in evidence_lines[:4]:
                    sections.append(f"  Evidence: {line}")
        if application_notes:
            sections.append("Additional deployment observations:")
            for note in application_notes[:10]:
                sections.append(f"- {note}")

        sections.extend(
            [
                "",
                "## 4. Under-explored Innovation Opportunities",
            ]
        )
        if innovation_notes:
            for note in innovation_notes[:16]:
                sections.append(f"- {note}")
        else:
            sections.extend(
                [
                    "- Opportunity A: unified intermediate representations for cross-scenario transfer.",
                    "- Opportunity B: causality-aware evaluation under distribution shift.",
                    "- Opportunity C: low-resource deployment architecture for broader real-world adoption.",
                    "- Opportunity D: graph priors fused with generation for reliable relation reasoning.",
                ]
            )

        sections.extend(
            [
                "",
                "## 5. Summary",
                (
                    f"For '{query}', the evidence suggests a clear trajectory from seminal work to sustained extensions and growing deployment. "
                    "The next value frontier is the combination of stronger evaluation, robust transfer, and lower deployment cost."
                ),
                "- Conclusion 1: continuation work has expanded capability, efficiency, and portability in parallel.",
                "- Conclusion 2: deployment already exists, but long-horizon stability still needs stronger proof.",
                "- Conclusion 3: high-impact innovation now lies in architecture integration plus evaluation upgrades.",
            ]
        )

        sections.extend(
            [
                "",
                "## 6. Reference Papers (Factual Listing)",
                (
                    f"The following references come from the current retrieved sample, ranked by citation count "
                    f"({len(all_papers)} total papers, showing {len(references)}):"
                ),
            ]
        )
        for index, item in enumerate(references, start=1):
            sections.append(f"{index}. {self._format_paper_reference_line(item, language='en')}")
        if not references:
            sections.append("- No citable papers are available in the current sample.")
        return "\n".join(sections).strip() + "\n"

    @staticmethod
    def _dedupe_report_lines(
        lines: list[str],
        *,
        limit: int,
        language: str,
    ) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for raw_line in lines:
            normalized = InsightExplorationService._sanitize_report_line(raw_line, language=language)
            if not normalized:
                continue
            key = re.sub(r"\s+", " ", normalized).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
            if len(deduped) >= max(1, int(limit)):
                break
        return deduped

    @staticmethod
    def _sanitize_report_line(text: object, *, language: str) -> str:
        safe = str(text or "").strip()
        if not safe:
            return ""
        noise_patterns = [
            r"\bsub[- ]?agent(s)?\b",
            r"\bagent(s)?\b",
            r"\bworkflow\b",
            r"\bcheckpoint(_\d+)?\b",
            r"\borchestrated\b",
            r"\bround\s*\d+\b",
            r"第\s*\d+\s*轮",
            r"子代理",
            r"多智能体",
            r"智能体",
            r"工作流",
            r"协商",
            r"工具调用",
        ]
        for pattern in noise_patterns:
            safe = re.sub(pattern, "", safe, flags=re.IGNORECASE)
        safe = re.sub(r"\[[^\]]{0,16}\]", "", safe)
        safe = re.sub(r"\s+", " ", safe).strip(" -:：;；,.。")
        if not safe:
            return ""
        max_chars = 380 if str(language or "").strip().lower() == "zh" else 420
        if len(safe) > max_chars:
            safe = f"{safe[:max(1, max_chars - 3)].rstrip()}..."
        return safe

    @staticmethod
    def _summarize_abstract_text(text: object, *, max_chars: int) -> str:
        safe = str(text or "").strip()
        if not safe:
            return ""
        safe = re.sub(r"\s+", " ", safe)
        limit = max(40, int(max_chars))
        if len(safe) <= limit:
            return safe
        return f"{safe[: max(1, limit - 3)].rstrip()}..."

    @staticmethod
    def _format_paper_reference_line(item: dict[str, Any], *, language: str) -> str:
        title = str(item.get("title") or "Unknown title").strip() or "Unknown title"
        year = InsightExplorationService._safe_int(item.get("year"), 0)
        citation_count = InsightExplorationService._safe_int(item.get("citation_count"), 0)
        venue = str(item.get("venue") or "Unknown").strip() or "Unknown"
        if language == "zh":
            return f"{title}（{year or '年份未知'}，引用 {citation_count}，来源 {venue}）"
        return f"{title} ({year or 'year unknown'}, citations {citation_count}, venue {venue})"

    @staticmethod
    def _infer_application_clusters(
        papers: list[dict[str, Any]],
        *,
        language: str,
    ) -> list[dict[str, Any]]:
        cluster_specs = [
            {
                "id": "healthcare",
                "name_zh": "医疗健康",
                "name_en": "Healthcare",
                "keywords": ("medical", "clinical", "diagnosis", "hospital", "healthcare", "medicine", "医疗", "临床"),
            },
            {
                "id": "finance",
                "name_zh": "金融与风控",
                "name_en": "Finance and Risk",
                "keywords": ("finance", "trading", "portfolio", "credit", "risk", "bank", "金融", "风控"),
            },
            {
                "id": "industry",
                "name_zh": "工业与制造",
                "name_en": "Industry and Manufacturing",
                "keywords": ("industrial", "manufacturing", "factory", "process control", "工厂", "制造", "工业"),
            },
            {
                "id": "robotics",
                "name_zh": "机器人与自动驾驶",
                "name_en": "Robotics and Autonomous Systems",
                "keywords": ("robot", "autonomous", "driving", "navigation", "embodied", "机器人", "自动驾驶"),
            },
            {
                "id": "internet",
                "name_zh": "搜索推荐与内容系统",
                "name_en": "Search, Recommendation, and Content",
                "keywords": ("search", "recommendation", "retrieval", "ranking", "ads", "推荐", "搜索", "排序"),
            },
            {
                "id": "science",
                "name_zh": "科研工具与知识发现",
                "name_en": "Scientific Discovery and Tooling",
                "keywords": ("scientific", "discovery", "knowledge graph", "literature", "科研", "知识图谱", "论文"),
            },
        ]
        scored: list[dict[str, Any]] = []
        for spec in cluster_specs:
            evidence: list[str] = []
            for item in papers:
                title = str(item.get("title") or "").strip()
                abstract = str(item.get("abstract") or "").strip()
                if not title and not abstract:
                    continue
                haystack = f"{title} {abstract}".lower()
                if not any(str(keyword).lower() in haystack for keyword in spec["keywords"]):
                    continue
                evidence.append(
                    InsightExplorationService._format_paper_reference_line(
                        item,
                        language=language,
                    )
                )
                if len(evidence) >= 6:
                    break
            if not evidence:
                continue
            scored.append(
                {
                    "name": spec["name_zh"] if language == "zh" else spec["name_en"],
                    "evidence": evidence,
                    "score": len(evidence),
                }
            )
        scored.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
        return scored

    async def _stream_markdown(
        self,
        *,
        markdown: str,
        callback: StreamCallback,
        section: str,
        start_accumulated: int = 0,
    ) -> None:
        chunk_size = 180
        accumulated = max(0, int(start_accumulated or 0))
        for start in range(0, len(markdown), chunk_size):
            chunk = markdown[start:start + chunk_size]
            accumulated += len(chunk)
            await callback(
                {
                    "section": section,
                    "chunk": chunk,
                    "accumulated_chars": accumulated,
                    "done": False,
                }
            )
            await asyncio.sleep(0.02)
        await callback(
            {
                "section": section,
                "chunk": "",
                "accumulated_chars": accumulated,
                "done": True,
            }
        )

    def _persist_artifacts(self, *, session_id: str, markdown: str, language: str) -> dict[str, str]:
        output_dir = self.report_root / session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "insight.md"
        md_path.write_text(markdown, encoding="utf-8")

        pdf_path = output_dir / "insight.pdf"
        if _REPORTLAB_AVAILABLE:
            try:
                pdf_path = self.render_markdown_pdf(
                    markdown=markdown,
                    pdf_path=pdf_path,
                    language=language,
                )
            except Exception:  # noqa: BLE001
                pdf_path = Path("")
        else:
            pdf_path = Path("")

        return {
            "markdown_path": str(md_path),
            "pdf_path": str(pdf_path) if str(pdf_path).strip() else "",
        }

    def render_markdown_pdf(
        self,
        *,
        markdown: str,
        pdf_path: Path,
        language: str | None = None,
    ) -> Path:
        safe_markdown = str(markdown or "").strip()
        if not safe_markdown:
            raise ValueError("insight_markdown_not_ready")

        target_path = Path(pdf_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        safe_language = str(language or "").strip().lower()
        if safe_language not in {"zh", "en"}:
            safe_language = "zh"

        if not _REPORTLAB_AVAILABLE:
            raise RuntimeError("insight_pdf_renderer_unavailable")

        self._write_pdf(
            markdown=safe_markdown,
            pdf_path=target_path,
            language=safe_language,
        )
        return target_path

    def _write_pdf(self, *, markdown: str, pdf_path: Path, language: str) -> None:
        assert _REPORTLAB_AVAILABLE and canvas is not None and A4 is not None
        base_font = "Helvetica"
        heading_font = "Helvetica-Bold"
        code_font = "Courier"
        emulate_heading_bold = False
        if language == "zh":
            try:
                assert pdfmetrics is not None and UnicodeCIDFont is not None
                pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
                base_font = "STSong-Light"
                heading_font = "STSong-Light"
                emulate_heading_bold = True
            except Exception:  # noqa: BLE001
                base_font = "Helvetica"
                heading_font = "Helvetica-Bold"
                emulate_heading_bold = False

        doc = canvas.Canvas(str(pdf_path), pagesize=A4)
        width, height = A4
        margin_left = 42
        margin_right = 42
        margin_top = 42
        margin_bottom = 45
        content_width = max(120, width - margin_left - margin_right)
        y = height - margin_top
        in_code_block = False

        def reset_page() -> None:
            nonlocal y
            doc.showPage()
            y = height - margin_top
            doc.setFont(base_font, 11)

        def ensure_space(required_height: float) -> None:
            nonlocal y
            if y - max(0.0, required_height) < margin_bottom:
                reset_page()

        def draw_single_line(
            text: str,
            *,
            x: float,
            font_name: str,
            font_size: int,
            line_height: int,
            bold: bool = False,
        ) -> None:
            nonlocal y
            ensure_space(float(line_height))
            doc.setFont(font_name, font_size)
            doc.drawString(x, y, text)
            if bold:
                doc.drawString(x + 0.28, y, text)
            y -= line_height

        def draw_wrapped_text(
            text: str,
            *,
            font_name: str,
            font_size: int,
            line_height: int,
            indent: float = 0.0,
            first_prefix: str = "",
            space_before: int = 0,
            space_after: int = 0,
            heading_bold: bool = False,
        ) -> None:
            nonlocal y
            cleaned = self._clean_markdown_inline(text)
            if not cleaned and not first_prefix:
                y -= max(0, space_after)
                return

            if space_before > 0:
                ensure_space(float(space_before))
                y -= space_before

            start_x = margin_left + max(0.0, indent)
            available_width = max(80.0, content_width - max(0.0, indent))
            prefix_width = self._measure_text_width(first_prefix, font_name=font_name, font_size=font_size) if first_prefix else 0.0

            if first_prefix:
                wrapped = self._wrap_text_by_width(
                    cleaned,
                    font_name=font_name,
                    font_size=font_size,
                    max_width=max(40.0, available_width - prefix_width),
                )
                if not wrapped:
                    wrapped = [""]
                draw_single_line(
                    f"{first_prefix}{wrapped[0]}",
                    x=start_x,
                    font_name=font_name,
                    font_size=font_size,
                    line_height=line_height,
                    bold=heading_bold,
                )
                for segment in wrapped[1:]:
                    draw_single_line(
                        segment,
                        x=start_x + prefix_width,
                        font_name=font_name,
                        font_size=font_size,
                        line_height=line_height,
                        bold=heading_bold,
                    )
            else:
                wrapped = self._wrap_text_by_width(
                    cleaned,
                    font_name=font_name,
                    font_size=font_size,
                    max_width=available_width,
                )
                if not wrapped:
                    wrapped = [""]
                for segment in wrapped:
                    draw_single_line(
                        segment,
                        x=start_x,
                        font_name=font_name,
                        font_size=font_size,
                        line_height=line_height,
                        bold=heading_bold,
                    )

            if space_after > 0:
                y -= space_after

        doc.setFont(base_font, 11)
        for raw_line in markdown.splitlines():
            line = str(raw_line or "").rstrip()
            stripped = line.strip()

            if stripped.startswith("```"):
                in_code_block = not in_code_block
                y -= 3
                continue

            if in_code_block:
                draw_wrapped_text(
                    line,
                    font_name=code_font,
                    font_size=9,
                    line_height=13,
                    indent=12,
                    space_before=0,
                    space_after=1,
                )
                continue

            if not stripped:
                y -= 7
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                level = max(1, min(6, len(heading_match.group(1))))
                text = heading_match.group(2).strip()
                heading_size_map = {1: 18, 2: 15, 3: 13, 4: 12, 5: 11, 6: 11}
                heading_leading_map = {1: 24, 2: 20, 3: 18, 4: 16, 5: 15, 6: 15}
                heading_before_map = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 4}
                heading_after_map = {1: 4, 2: 3, 3: 2, 4: 2, 5: 2, 6: 1}
                draw_wrapped_text(
                    text,
                    font_name=heading_font,
                    font_size=heading_size_map[level],
                    line_height=heading_leading_map[level],
                    space_before=heading_before_map[level],
                    space_after=heading_after_map[level],
                    heading_bold=emulate_heading_bold,
                )
                continue

            unordered_match = re.match(r"^\s*[-*+]\s+(.+)$", stripped)
            if unordered_match:
                draw_wrapped_text(
                    unordered_match.group(1),
                    font_name=base_font,
                    font_size=11,
                    line_height=15,
                    first_prefix="- ",
                    indent=0,
                    space_before=0,
                    space_after=1,
                )
                continue

            ordered_match = re.match(r"^\s*(\d+)[.)]\s+(.+)$", stripped)
            if ordered_match:
                prefix = f"{ordered_match.group(1)}. "
                draw_wrapped_text(
                    ordered_match.group(2),
                    font_name=base_font,
                    font_size=11,
                    line_height=15,
                    first_prefix=prefix,
                    indent=0,
                    space_before=0,
                    space_after=1,
                )
                continue

            if stripped in {"---", "***", "___"}:
                ensure_space(8)
                doc.setLineWidth(0.6)
                doc.line(margin_left, y, width - margin_right, y)
                y -= 8
                continue

            draw_wrapped_text(
                line,
                font_name=base_font,
                font_size=11,
                line_height=16,
                space_before=0,
                space_after=2,
            )
        doc.save()

    @staticmethod
    def _clean_markdown_inline(text: str) -> str:
        safe = str(text or "").replace("\t", "    ").strip()
        if not safe:
            return ""
        safe = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1 (\2)", safe)
        safe = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", safe)
        safe = re.sub(r"`([^`]*)`", r"\1", safe)
        safe = re.sub(r"\*\*(.+?)\*\*", r"\1", safe)
        safe = re.sub(r"__(.+?)__", r"\1", safe)
        safe = re.sub(r"\*(.+?)\*", r"\1", safe)
        safe = re.sub(r"_(.+?)_", r"\1", safe)
        safe = re.sub(r"~~(.+?)~~", r"\1", safe)
        return safe.strip()

    @staticmethod
    def _measure_text_width(text: str, *, font_name: str, font_size: int) -> float:
        safe_text = str(text or "")
        if not safe_text:
            return 0.0
        if pdfmetrics is not None:
            try:
                return float(pdfmetrics.stringWidth(safe_text, font_name, font_size))
            except Exception:  # noqa: BLE001
                pass
        return float(len(safe_text)) * float(font_size) * 0.55

    @staticmethod
    def _wrap_text_by_width(
        text: str,
        *,
        font_name: str,
        font_size: int,
        max_width: float,
    ) -> list[str]:
        safe = str(text or "")
        if not safe:
            return [""]
        width_limit = max(40.0, float(max_width))
        lines: list[str] = []
        current = ""

        for char in safe:
            candidate = f"{current}{char}"
            candidate_width = InsightExplorationService._measure_text_width(
                candidate,
                font_name=font_name,
                font_size=font_size,
            )
            if current and candidate_width > width_limit:
                lines.append(current.rstrip())
                current = char.lstrip()
                continue
            current = candidate

        if current or not lines:
            lines.append(current.rstrip())
        return [line for line in lines if line] or [""]

    def _build_summary(
        self,
        *,
        language: str,
        extension_count: int,
        role_count: int,
        rounds: int,
        base_papers: int,
    ) -> str:
        del role_count, rounds
        if language == "zh":
            return (
                "报告已完成：围绕鼻祖论文、延续工作、当前应用、创新空白、总结与引用清单展开。"
                f"本次样本包含基础论文 {base_papers} 篇，扩展新增 {extension_count} 篇。"
            )
        return (
            "Report completed with six sections: seminal origin, continuation chain, current deployment, "
            f"innovation gaps, summary, and factual references ({base_papers} base papers, {extension_count} expanded papers)."
        )

    @staticmethod
    def _format_line(language: str, *, zh: str, en: str) -> str:
        return zh if language == "zh" else en

    @staticmethod
    def _top_papers_for_prompt(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        sorted_items = sorted(
            [dict(item) for item in items if isinstance(item, dict)],
            key=lambda item: (
                InsightExplorationService._safe_int(item.get("citation_count"), 0),
                InsightExplorationService._safe_int(item.get("year"), 0),
            ),
            reverse=True,
        )
        return sorted_items[: max(1, limit)]

    @staticmethod
    def _merge_papers(
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in (primary, secondary):
            for item in source:
                if not isinstance(item, dict):
                    continue
                paper_id = str(item.get("paper_id") or "").strip().lower()
                title = re.sub(r"\s+", " ", str(item.get("title") or "").strip().lower())
                key = paper_id or f"title:{title}"
                if not key:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= max(1, limit):
                    return merged
        return merged

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(math.floor(float(value)))
        except (TypeError, ValueError):
            return default


@lru_cache
def get_insight_exploration_service() -> InsightExplorationService:
    return InsightExplorationService()
