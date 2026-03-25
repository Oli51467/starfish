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
from time import perf_counter
from typing import Any, Awaitable, Callable

from core.settings import get_settings
from core.llm_client import chat, get_client, is_configured
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
_DEFAULT_ARTIFACT_PDF_TIMEOUT_SECONDS = 15.0
_REPORT_MIN_CHARS_ZH = 10000
_REPORT_TARGET_CHARS_ZH = 12000
_REPORT_MIN_CHARS_EN = 7000
_REPORT_TARGET_CHARS_EN = 9000
_REPORT_EXPANSION_MAX_ROUNDS = 3
_REPORT_BASE_MAX_TOKENS = 3200
_REPORT_EXPANSION_MAX_TOKENS = 2400


@dataclass(frozen=True)
class _RoleSpec:
    role_id: str
    title_zh: str
    title_en: str
    focus: str


@dataclass(frozen=True)
class _ComposeMarkdownResult:
    markdown: str
    streamed: bool = False
    streamed_chars: int = 0


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
        configured_pdf_timeout = float(
            getattr(self.settings, "insight_pdf_render_timeout_seconds", _DEFAULT_ARTIFACT_PDF_TIMEOUT_SECONDS)
            or _DEFAULT_ARTIFACT_PDF_TIMEOUT_SECONDS
        )
        self.artifact_pdf_timeout_seconds = max(8.0, min(90.0, configured_pdf_timeout))

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

        compose_started_at = perf_counter()
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=safe_session_id,
            event_type="insight_report_compose_started",
        )
        stream_started_at: float | None = None
        if stream_callback is not None:
            stream_started_at = perf_counter()
            await self._emit_lifecycle_event(
                stream_callback=stream_callback,
                session_id=safe_session_id,
                event_type="insight_report_stream_started",
            )
        compose_result = await self._compose_markdown(
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
            stream_callback=stream_callback,
            stream_start_accumulated=0,
        )
        markdown = str(compose_result.markdown or "")
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=safe_session_id,
            event_type="insight_report_compose_completed",
            stage_started_at=compose_started_at,
            details={
                "markdown_chars": len(markdown),
            },
        )

        stream_completed_chars = 0
        if stream_callback is not None:
            if compose_result.streamed:
                stream_completed_chars = max(
                    int(compose_result.streamed_chars or 0),
                    len(markdown),
                )
                await self._emit_stream_done(
                    callback=stream_callback,
                    section="insight_markdown",
                    accumulated_chars=stream_completed_chars,
                )
            else:
                await self._stream_markdown(
                    markdown=markdown,
                    callback=stream_callback,
                    section="insight_markdown",
                )
                stream_completed_chars = len(markdown)
            await self._emit_lifecycle_event(
                stream_callback=stream_callback,
                session_id=safe_session_id,
                event_type="insight_report_stream_completed",
                stage_started_at=stream_started_at or perf_counter(),
                accumulated_chars=stream_completed_chars,
                details={
                    "markdown_chars": len(markdown),
                },
            )

        artifact_started_at = perf_counter()
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=safe_session_id,
            event_type="insight_artifact_persist_started",
            accumulated_chars=stream_completed_chars,
        )
        markdown_path = await asyncio.to_thread(
            self._persist_markdown_artifact,
            session_id=safe_session_id,
            markdown=markdown,
        )
        pdf_path = ""
        artifact_warning = ""
        try:
            pdf_path = await asyncio.wait_for(
                asyncio.to_thread(
                    self._persist_pdf_artifact,
                    markdown=markdown,
                    markdown_path=markdown_path,
                    language=language,
                ),
                timeout=float(self.artifact_pdf_timeout_seconds),
            )
        except TimeoutError:
            artifact_warning = "pdf_generation_timeout"
        except Exception:
            artifact_warning = "pdf_generation_failed"
        artifact = {
            "markdown_path": str(markdown_path or ""),
            "pdf_path": str(pdf_path or ""),
        }
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=safe_session_id,
            event_type="insight_artifact_persist_completed",
            stage_started_at=artifact_started_at,
            accumulated_chars=stream_completed_chars,
            level="warning" if artifact_warning else "info",
            details={
                "markdown_path": artifact["markdown_path"],
                "pdf_path": artifact["pdf_path"],
                "warning": artifact_warning,
            },
        )

        finalize_started_at = perf_counter()
        summary = self._build_summary(
            language=language,
            extension_count=len(extension_papers),
            role_count=len(active_roles),
            rounds=rounds,
            base_papers=len(normalized_papers),
        )
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=safe_session_id,
            event_type="insight_finalize_completed",
            stage_started_at=finalize_started_at,
            accumulated_chars=stream_completed_chars,
            details={
                "pdf_available": bool(str(artifact.get("pdf_path") or "").strip()),
                "warning": artifact_warning,
            },
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

        compose_started_at = perf_counter()
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=session_id,
            event_type="insight_report_compose_started",
            accumulated_chars=streamed_chars,
        )
        stream_started_at: float | None = None
        if stream_callback is not None:
            stream_started_at = perf_counter()
            await self._emit_lifecycle_event(
                stream_callback=stream_callback,
                session_id=session_id,
                event_type="insight_report_stream_started",
                accumulated_chars=streamed_chars,
            )
        compose_result = await self._compose_markdown(
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
            stream_callback=stream_callback,
            stream_start_accumulated=streamed_chars,
        )
        markdown = str(compose_result.markdown or "")
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=session_id,
            event_type="insight_report_compose_completed",
            stage_started_at=compose_started_at,
            accumulated_chars=streamed_chars,
            details={
                "markdown_chars": len(markdown),
            },
        )
        if stream_callback is not None:
            if compose_result.streamed:
                streamed_chars = max(
                    int(compose_result.streamed_chars or 0),
                    len(markdown),
                )
                await self._emit_stream_done(
                    callback=stream_callback,
                    section="insight_markdown",
                    accumulated_chars=streamed_chars,
                )
            else:
                await self._stream_markdown(
                    markdown=markdown,
                    callback=stream_callback,
                    section="insight_markdown",
                    start_accumulated=streamed_chars,
                )
                streamed_chars += len(markdown)
        else:
            streamed_chars = len(markdown)
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=session_id,
            event_type="insight_report_stream_completed",
            stage_started_at=stream_started_at or perf_counter(),
            accumulated_chars=streamed_chars,
            details={
                "markdown_chars": len(markdown),
            },
        )

        artifact_started_at = perf_counter()
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=session_id,
            event_type="insight_artifact_persist_started",
            accumulated_chars=streamed_chars,
        )
        markdown_path = await asyncio.to_thread(
            self._persist_markdown_artifact,
            session_id=session_id,
            markdown=markdown,
        )
        pdf_path = ""
        artifact_warning = ""
        try:
            pdf_path = await asyncio.wait_for(
                asyncio.to_thread(
                    self._persist_pdf_artifact,
                    markdown=markdown,
                    markdown_path=markdown_path,
                    language=language,
                ),
                timeout=float(self.artifact_pdf_timeout_seconds),
            )
        except TimeoutError:
            artifact_warning = "pdf_generation_timeout"
        except Exception:
            artifact_warning = "pdf_generation_failed"

        artifact = {
            "markdown_path": str(markdown_path or ""),
            "pdf_path": str(pdf_path or ""),
        }
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=session_id,
            event_type="insight_artifact_persist_completed",
            stage_started_at=artifact_started_at,
            accumulated_chars=streamed_chars,
            level="warning" if artifact_warning else "info",
            details={
                "markdown_path": artifact["markdown_path"],
                "pdf_path": artifact["pdf_path"],
                "warning": artifact_warning,
            },
        )

        finalize_started_at = perf_counter()
        summary = self._build_summary(
            language=language,
            extension_count=len(extension_papers),
            role_count=len(active_roles),
            rounds=rounds,
            base_papers=len(normalized_papers),
        )
        await self._emit_lifecycle_event(
            stream_callback=stream_callback,
            session_id=session_id,
            event_type="insight_finalize_completed",
            stage_started_at=finalize_started_at,
            accumulated_chars=streamed_chars,
            details={
                "pdf_available": bool(str(artifact.get("pdf_path") or "").strip()),
                "warning": artifact_warning,
            },
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
                                "You are a senior scientific analyst. "
                                "Write rigorous, evidence-grounded content only. "
                                "Do not mention workflows, agents, orchestration, rounds, or tool calls."
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
        evidence_cards = [
            {
                "id": f"E{index}",
                "title": str(item.get("title") or "Unknown title").strip() or "Unknown title",
                "year": self._safe_int(item.get("year"), 0),
                "venue": str(item.get("venue") or "Unknown").strip() or "Unknown",
                "citations": self._safe_int(item.get("citation_count"), 0),
                "abstract_hint": self._summarize_abstract_text(item.get("abstract"), max_chars=180),
            }
            for index, item in enumerate(top_papers, start=1)
        ]
        context = {
            "query": query,
            "round": round_index,
            "role": role_name,
            "focus": role.focus,
            "report_focus": role_focus,
            "objective": str(objective or "").strip(),
            "graph_stats": graph_stats,
            "evidence_cards": evidence_cards,
            "history_memory": history_memory[:2],
            "session_hypotheses": (session_memory.get("hypotheses") or [])[-2:],
            "session_critic_notes": (session_memory.get("critic_notes") or [])[-2:],
        }
        if language == "zh":
            return (
                "你是科研分析写作助手，请输出严谨、可核验、可执行的中文分析。"
                f"当前角色：{role_name}；本轮重点：{role_focus}。"
                "严格要求："
                "1) 只使用上下文给出的证据，不得臆造论文；"
                "2) 不得出现工作流、智能体、子代理、轮次、工具调用等过程描述；"
                "3) 必须给出至少2条带证据编号(E1/E2...)的判断依据；"
                "4) 给出可执行建议和一个主要不确定性。"
                "输出格式固定为四行（不要额外小标题）："
                "核心判断：..."
                "证据条目：...（示例：[E1] 论文名(年份)）"
                "可执行建议：..."
                "不确定性：..."
                f"上下文：{context}"
            )
        return (
            "You are a scientific writing analyst and must produce rigorous, evidence-grounded English analysis. "
            f"Role: {role_name}. Focus: {role_focus}. "
            "Strict rules: use only provided evidence, no fabricated papers, no workflow/agent/tool narration, "
            "include at least two evidence-linked judgments with E1/E2 markers, add executable recommendation and one uncertainty. "
            "Output must be exactly four lines with these prefixes only: "
            "Core Judgment: ... "
            "Evidence: ... (example: [E1] Paper Title (Year)) "
            "Actionable Recommendation: ... "
            "Uncertainty: ... "
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
        del round_index
        total_papers = len(papers) + len(extension_papers)
        focus_label = self._resolve_role_report_focus(role_id=role.role_id, language=language)
        ranked = self._rank_papers_by_query_relevance(
            papers + extension_papers,
            query=query,
            limit=2,
        )
        top_item = ranked[0] if ranked else None
        evidence_line = self._format_paper_reference_line(top_item, language=language) if top_item else ""
        if language == "zh":
            return "\n".join(
                [
                    f"核心判断：围绕“{query}”的现有证据显示，{focus_label}是下一步最应优先验证的主线。",
                    (
                        "证据条目："
                        f"{evidence_line if evidence_line else '当前样本未提供可直接引用的高置信论文。'}"
                    ),
                    (
                        "可执行建议：先以2-3篇高相关论文构建最小证据链，"
                        "再设计可量化评测（准确率/时延/成本）的小规模试点。"
                    ),
                    (
                        "不确定性：样本规模目前为"
                        f"{total_papers}篇（图谱节点{graph_stats['node_count']}、关系{graph_stats['edge_count']}），"
                        "跨场景泛化结论仍需补充证据。"
                    ),
                ]
            )
        return (
            "\n".join(
                [
                    (
                        f"Core Judgment: For '{query}', the strongest next validation axis is {focus_label} "
                        "based on the current evidence scope."
                    ),
                    (
                        "Evidence: "
                        f"{evidence_line if evidence_line else 'No high-confidence paper is directly citable in the current sample.'}"
                    ),
                    (
                        "Actionable Recommendation: Start with a minimal evidence chain from 2-3 highly relevant papers "
                        "and evaluate by measurable metrics (quality, latency, and cost)."
                    ),
                    (
                        "Uncertainty: The sample size is "
                        f"{total_papers} papers ({graph_stats['node_count']} nodes, {graph_stats['edge_count']} relations), "
                        "so cross-domain generalization remains uncertain."
                    ),
                ]
            )
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
        stream_callback: StreamCallback | None = None,
        stream_start_accumulated: int = 0,
    ) -> _ComposeMarkdownResult:
        del input_type, active_roles, rounds
        safe_language = "zh" if language == "zh" else "en"
        all_papers = self._merge_papers(
            base_papers,
            extension_papers,
            limit=max(1, len(base_papers) + len(extension_papers)),
        )
        ranked_papers = self._rank_papers_by_query_relevance(
            all_papers,
            query=query,
            limit=min(36, max(1, len(all_papers))),
        )
        focus_pool = ranked_papers if ranked_papers else self._top_papers_for_prompt(all_papers, limit=min(24, max(1, len(all_papers))))
        focus_papers = focus_pool[: min(24, max(1, len(focus_pool)))] if focus_pool else []

        papers_sorted_by_year = sorted(
            [item for item in focus_papers if self._safe_int(item.get("year"), 0) > 0],
            key=lambda item: (
                self._safe_int(item.get("year"), 0),
                -self._safe_int(item.get("citation_count"), 0),
                str(item.get("title") or "").lower(),
            ),
        )
        papers_sorted_by_citation = sorted(
            focus_papers,
            key=lambda item: (
                self._safe_int(item.get("citation_count"), 0),
                self._safe_int(item.get("year"), 0),
            ),
            reverse=True,
        )
        founder_source = papers_sorted_by_year[:12] if papers_sorted_by_year else papers_sorted_by_citation[:12]
        founder_candidates = founder_source[:3]
        founder_primary = founder_candidates[0] if founder_candidates else None

        decisions = self._dedupe_report_lines(session_memory.get("decisions") or [], limit=32, language=safe_language)
        hypotheses = self._dedupe_report_lines(session_memory.get("hypotheses") or [], limit=16, language=safe_language)
        critic_notes = self._dedupe_report_lines(session_memory.get("critic_notes") or [], limit=16, language=safe_language)
        history_notes = self._dedupe_report_lines(history_memory or [], limit=6, language=safe_language)
        extension_signals = self._dedupe_report_lines(extension_notes or [], limit=6, language=safe_language)
        role_signals = self._dedupe_report_lines(
            decisions + hypotheses + critic_notes + history_notes + extension_signals,
            limit=24,
            language=safe_language,
        )
        innovation_points = self._dedupe_report_lines(
            hypotheses + critic_notes,
            limit=10,
            language=safe_language,
        )
        application_clusters = self._infer_application_clusters(focus_papers, language=safe_language)

        reference_seed = focus_papers if focus_papers else all_papers
        reference_candidates = self._top_papers_for_prompt(reference_seed, limit=min(24, max(1, len(reference_seed))))
        reference_catalog = self._build_reference_catalog(reference_candidates, language=safe_language)

        llm_result = await self._compose_markdown_with_llm(
            language=safe_language,
            query=query,
            graph_stats=graph_stats,
            all_paper_count=len(all_papers),
            founder_candidates=founder_candidates,
            timeline_papers=papers_sorted_by_year[:14],
            application_clusters=application_clusters[:6],
            role_signals=role_signals[:14],
            innovation_points=innovation_points[:8],
            reference_catalog=reference_catalog,
            stream_callback=stream_callback,
            stream_start_accumulated=stream_start_accumulated,
        )
        if llm_result.markdown:
            return llm_result

        fallback_markdown = self._compose_markdown_fallback(
            language=safe_language,
            query=query,
            graph_stats=graph_stats,
            all_paper_count=len(all_papers),
            founder_primary=founder_primary,
            founder_candidates=founder_candidates,
            timeline_papers=papers_sorted_by_year[:12],
            role_signals=role_signals[:12],
            application_clusters=application_clusters[:6],
            innovation_points=innovation_points[:8],
            critic_notes=critic_notes[:6],
            reference_catalog=reference_catalog,
        )
        fallback_markdown = self._expand_markdown_with_evidence_appendix(
            markdown=fallback_markdown,
            language=safe_language,
            query=query,
            reference_catalog=reference_catalog,
            application_clusters=application_clusters[:8],
            role_signals=role_signals[:16],
            innovation_points=innovation_points[:10],
        )
        return _ComposeMarkdownResult(markdown=fallback_markdown, streamed=False, streamed_chars=0)

    async def _compose_markdown_with_llm(
        self,
        *,
        language: str,
        query: str,
        graph_stats: dict[str, int],
        all_paper_count: int,
        founder_candidates: list[dict[str, Any]],
        timeline_papers: list[dict[str, Any]],
        application_clusters: list[dict[str, Any]],
        role_signals: list[str],
        innovation_points: list[str],
        reference_catalog: list[dict[str, Any]],
        stream_callback: StreamCallback | None = None,
        stream_start_accumulated: int = 0,
    ) -> _ComposeMarkdownResult:
        if not is_configured():
            return _ComposeMarkdownResult(markdown="", streamed=False, streamed_chars=0)

        context = {
            "query": query,
            "graph_stats": {
                "node_count": int(graph_stats.get("node_count") or 0),
                "edge_count": int(graph_stats.get("edge_count") or 0),
                "paper_node_count": int(graph_stats.get("paper_node_count") or 0),
                "paper_count": int(all_paper_count),
            },
            "founder_candidates": [
                self._format_paper_reference_line(item, language=language)
                for item in founder_candidates
            ],
            "timeline_evidence": [
                self._format_paper_reference_line(item, language=language)
                for item in timeline_papers
            ],
            "application_clusters": application_clusters,
            "role_signals": role_signals,
            "innovation_points": innovation_points,
            "references": reference_catalog,
        }

        if language == "zh":
            user_prompt = (
                "请基于下方证据，生成一份中文科研风格 Markdown 报告。\n"
                "硬性约束：\n"
                "1) 只能使用给定 references 中的信息，禁止臆造论文或数值；\n"
                "2) 严禁出现 workflow/agent/子代理/协同轮次/工具调用等过程描述；\n"
                "3) 全文只用中文叙述（论文标题可保留原文）；\n"
                "4) 每个关键判断后必须给文内引用编号，如 [R3] 或 [R3][R8]；\n"
                "5) 避免模板化重复句，不要输出空洞口号；\n"
                "6) 正文（不含参考文献）不少于 10000 字，目标 12000 字左右；\n"
                "7) 每个一级章节不少于 800 字，摘要不少于 600 字。\n"
                "请使用以下固定结构标题：\n"
                f"# 研究洞察报告：{query}\n"
                "## 摘要\n"
                "## 1. 研究问题界定与评价框架\n"
                "## 2. 研究起源与关键演进\n"
                "## 3. 方法谱系与机制拆解\n"
                "## 4. 关键论文深读与证据矩阵\n"
                "## 5. 证据对照、分歧与可证伪性\n"
                "## 6. 应用落地、产业化与商业模式\n"
                "## 7. 工程实现、算力成本与系统约束\n"
                "## 8. 创新机会、研究议程与实验设计\n"
                "## 9. 风险、伦理与治理建议\n"
                "## 10. 结论与执行路线图\n"
                "## 参考文献\n"
                "“关键论文深读与证据矩阵”至少逐篇分析 8 篇核心论文，并比较其方法差异与适用边界。\n"
                "“证据对照、分歧与可证伪性”必须包含至少 1 个可执行对照实验设计。\n"
                "其中“参考文献”仅列正文实际引用过的条目，格式为：\n"
                "- [R1] Title（Year，Venue，引用 N）\n"
                "如果证据不足，请明确写“当前证据不足以支持该结论”。\n"
                f"证据上下文(JSON)：{json.dumps(context, ensure_ascii=False)}"
            )
        else:
            user_prompt = (
                "Generate a scientific-style Markdown report strictly from the evidence below.\n"
                "Hard constraints:\n"
                "1) Use only facts from the provided references; do not invent papers or numbers.\n"
                "2) Never mention workflow, agents, orchestration rounds, or tool calls.\n"
                "3) Keep language consistent in English.\n"
                "4) Every key claim must carry in-text citations, e.g., [R3] or [R3][R8].\n"
                "5) Avoid repetitive template filler and generic slogans.\n"
                "6) Main body (excluding references) must be >= 7000 characters, target around 9000.\n"
                "7) Each top-level section should be substantial (typically >= 500 characters).\n"
                "Use this exact heading structure:\n"
                f"# Research Insight Report: {query}\n"
                "## Abstract\n"
                "## 1. Problem Framing and Evaluation Criteria\n"
                "## 2. Research Origin and Evolution\n"
                "## 3. Method Taxonomy and Mechanistic Decomposition\n"
                "## 4. Deep Reading of Core Papers and Evidence Matrix\n"
                "## 5. Evidence Contradictions and Falsifiability\n"
                "## 6. Applications, Adoption, and Business Implications\n"
                "## 7. Engineering Constraints, Compute, and Cost\n"
                "## 8. Innovation Opportunities and Research Agenda\n"
                "## 9. Risks, Ethics, and Governance\n"
                "## 10. Conclusion and Execution Roadmap\n"
                "## References\n"
                "In the References section, include only cited entries with format:\n"
                "- [R1] Title (Year, Venue, citations N)\n"
                "If evidence is insufficient, explicitly state: 'Current evidence is insufficient to support this claim.'\n"
                f"Evidence context (JSON): {json.dumps(context, ensure_ascii=False)}"
            )

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a senior research report writer. "
                        "Deliver precise, evidence-constrained, publication-style synthesis."
                    ),
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ]
            raw_content = ""
            streamed_chars = 0
            streamed = False
            if stream_callback is not None:
                raw_content, streamed_chars = await asyncio.wait_for(
                    self._stream_chat_completion_content(
                        messages=messages,
                        temperature=0.15,
                        timeout_seconds=120,
                        max_tokens=_REPORT_BASE_MAX_TOKENS,
                        stream_callback=stream_callback,
                        section="insight_markdown",
                        start_accumulated=stream_start_accumulated,
                    ),
                    timeout=180,
                )
                streamed = bool(raw_content)
            else:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        chat,
                        messages,
                        temperature=0.15,
                        timeout=120,
                        max_tokens=_REPORT_BASE_MAX_TOKENS,
                    ),
                    timeout=140,
                )
                raw_content = str(response.choices[0].message.content or "").strip()
                streamed_chars = 0
                streamed = False
            if not raw_content:
                return _ComposeMarkdownResult(markdown="", streamed=False, streamed_chars=0)
            cleaned = (
                self._normalize_streamed_report_markdown(raw_content, language=language)
                if streamed
                else self._clean_report_markdown(raw_content, language=language)
            )
            if not cleaned:
                return _ComposeMarkdownResult(markdown="", streamed=False, streamed_chars=0)
            refined_markdown, refined_streamed_chars = await self._expand_markdown_if_needed(
                language=language,
                query=query,
                context=context,
                markdown=cleaned,
                stream_callback=stream_callback,
                accumulated_chars=int(streamed_chars if streamed else 0),
            )
            final_markdown = self._ensure_reference_section(
                markdown=refined_markdown or cleaned,
                reference_catalog=reference_catalog,
                language=language,
            )
            if streamed:
                return _ComposeMarkdownResult(
                    markdown=final_markdown if final_markdown.endswith("\n") else f"{final_markdown}\n",
                    streamed=True,
                    streamed_chars=max(0, int(refined_streamed_chars or streamed_chars)),
                )
            return _ComposeMarkdownResult(
                markdown=final_markdown if final_markdown.endswith("\n") else f"{final_markdown}\n",
                streamed=False,
                streamed_chars=0,
            )
        except Exception:  # noqa: BLE001
            return _ComposeMarkdownResult(markdown="", streamed=False, streamed_chars=0)
        return _ComposeMarkdownResult(markdown="", streamed=False, streamed_chars=0)

    @staticmethod
    def _resolve_report_length_targets(language: str) -> tuple[int, int]:
        safe_language = str(language or "").strip().lower()
        if safe_language == "zh":
            return _REPORT_MIN_CHARS_ZH, _REPORT_TARGET_CHARS_ZH
        return _REPORT_MIN_CHARS_EN, _REPORT_TARGET_CHARS_EN

    @staticmethod
    def _report_body_char_count(markdown: str) -> int:
        safe = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
        if not safe:
            return 0
        body = re.split(r"\n##\s*(参考文献|references)\b", safe, maxsplit=1, flags=re.IGNORECASE)[0]
        body = re.sub(r"```[\s\S]*?```", " ", body)
        body = re.sub(r"`[^`]*`", " ", body)
        body = re.sub(r"\[[Rr]\d+\]", " ", body)
        body = re.sub(r"\s+", "", body)
        return len(body)

    def _build_report_expansion_prompt(
        self,
        *,
        language: str,
        query: str,
        markdown: str,
        context: dict[str, Any],
        current_chars: int,
        target_chars: int,
        round_index: int,
    ) -> str:
        safe_markdown = str(markdown or "").strip()
        heading_lines = re.findall(r"^##\s+.+$", safe_markdown, flags=re.MULTILINE)
        heading_snapshot = heading_lines[:18]
        reference_snapshot = [
            {
                "id": str(item.get("id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "year": int(item.get("year") or 0),
                "venue": str(item.get("venue") or "").strip(),
                "citations": int(item.get("citations") or 0),
            }
            for item in (context.get("references") or [])[:24]
            if isinstance(item, dict)
        ]
        excerpt = safe_markdown[-3200:]
        if language == "zh":
            return (
                "你正在续写同一份科研报告，请输出“仅追加的新内容”，用于插入到参考文献之前。\n"
                "要求：\n"
                "1) 不要重写已有段落，不要重复已有二级标题；\n"
                "2) 不要输出新的总标题（# ...）与“参考文献”章节；\n"
                "3) 每个关键判断必须带 [R*] 引用；\n"
                "4) 只能使用给定 references，禁止虚构；\n"
                "5) 新增内容应覆盖：机制细节、证据分歧、失败边界、工程约束、实验设计；\n"
                "6) 本次新增至少 2500 字，且新增至少 2 个二级标题。\n"
                f"当前正文约 {current_chars} 字，目标正文约 {target_chars} 字；本轮为第 {round_index} 次扩写。\n"
                f"主题：{query}\n"
                f"已有二级标题：{json.dumps(heading_snapshot, ensure_ascii=False)}\n"
                f"可用参考文献：{json.dumps(reference_snapshot, ensure_ascii=False)}\n"
                f"现有报告尾部片段：{excerpt}"
            )
        return (
            "You are extending the same research report. Output only NEW markdown content to append before References.\n"
            "Rules:\n"
            "1) Do not rewrite existing paragraphs and do not duplicate existing H2 headings.\n"
            "2) Do not output a new top title (# ...) and do not output a References section.\n"
            "3) Every key claim must include [R*] citations.\n"
            "4) Use only provided references; do not invent facts.\n"
            "5) Add depth on mechanisms, contradictory evidence, failure boundaries, engineering constraints, and experiments.\n"
            "6) Add at least 1800 characters this round and include at least two new H2 headings.\n"
            f"Current body length is about {current_chars} chars, target is {target_chars} chars. Expansion round: {round_index}.\n"
            f"Topic: {query}\n"
            f"Existing H2 headings: {json.dumps(heading_snapshot, ensure_ascii=False)}\n"
            f"Available references: {json.dumps(reference_snapshot, ensure_ascii=False)}\n"
            f"Tail excerpt of current report: {excerpt}"
        )

    @staticmethod
    def _normalize_report_expansion_chunk(chunk: str) -> str:
        safe = str(chunk or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not safe:
            return ""
        # Drop accidental duplicated title/reference headers from continuation outputs.
        safe = re.sub(r"^#\s+.+?$", "", safe, flags=re.MULTILINE)
        safe = re.sub(r"^##\s*(参考文献|references)\b.*$", "", safe, flags=re.IGNORECASE | re.MULTILINE)
        safe = re.sub(r"\n{3,}", "\n\n", safe).strip()
        return safe

    @staticmethod
    def _append_report_expansion(markdown: str, expansion_chunk: str) -> str:
        base = str(markdown or "").rstrip()
        chunk = str(expansion_chunk or "").strip()
        if not chunk:
            return base
        reference_match = re.search(r"^##\s*(参考文献|references)\b", base, flags=re.IGNORECASE | re.MULTILINE)
        if reference_match is None:
            return f"{base}\n\n{chunk}\n".strip()
        body = base[: reference_match.start()].rstrip()
        refs = base[reference_match.start() :].lstrip()
        return f"{body}\n\n{chunk}\n\n{refs}".strip()

    def _ensure_reference_section(
        self,
        *,
        markdown: str,
        reference_catalog: list[dict[str, Any]],
        language: str,
    ) -> str:
        safe = str(markdown or "").strip()
        if not safe:
            return ""
        has_reference_section = bool(
            re.search(
                r"^##\s*(参考文献|references)\b",
                safe,
                flags=re.IGNORECASE | re.MULTILINE,
            )
        )
        if has_reference_section:
            return safe
        references = self._format_reference_lines(reference_catalog=reference_catalog, language=language)
        if not references:
            return safe
        heading = "## 参考文献" if language == "zh" else "## References"
        return f"{safe}\n\n{heading}\n{references}".strip()

    @staticmethod
    def _format_reference_lines(reference_catalog: list[dict[str, Any]], *, language: str) -> str:
        lines: list[str] = []
        for item in reference_catalog:
            if not isinstance(item, dict):
                continue
            ref_id = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not ref_id or not title:
                continue
            year = int(item.get("year") or 0)
            venue = str(item.get("venue") or "Unknown").strip() or "Unknown"
            citations = int(item.get("citations") or 0)
            if language == "zh":
                lines.append(f"- [{ref_id}] {title}（{year or '年份未知'}，{venue}，引用 {citations}）")
            else:
                lines.append(f"- [{ref_id}] {title} ({year or 'year unknown'}, {venue}, citations {citations})")
        return "\n".join(lines).strip()

    async def _expand_markdown_if_needed(
        self,
        *,
        language: str,
        query: str,
        context: dict[str, Any],
        markdown: str,
        stream_callback: StreamCallback | None,
        accumulated_chars: int,
    ) -> tuple[str, int]:
        safe_markdown = str(markdown or "").strip()
        if not safe_markdown or not is_configured():
            return safe_markdown, max(0, int(accumulated_chars))
        min_chars, target_chars = self._resolve_report_length_targets(language)
        body_chars = self._report_body_char_count(safe_markdown)
        if body_chars >= min_chars:
            return safe_markdown, max(0, int(accumulated_chars))

        current_markdown = safe_markdown
        current_accumulated = max(0, int(accumulated_chars))
        for round_index in range(1, _REPORT_EXPANSION_MAX_ROUNDS + 1):
            body_chars = self._report_body_char_count(current_markdown)
            if body_chars >= min_chars:
                break
            prompt = self._build_report_expansion_prompt(
                language=language,
                query=query,
                markdown=current_markdown,
                context=context,
                current_chars=body_chars,
                target_chars=target_chars,
                round_index=round_index,
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a strict evidence-grounded research writer. "
                        "Expand analytical depth without changing existing conclusions."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            try:
                if stream_callback is not None:
                    raw_chunk, streamed_chars = await asyncio.wait_for(
                        self._stream_chat_completion_content(
                            messages=messages,
                            temperature=0.15,
                            timeout_seconds=110,
                            max_tokens=_REPORT_EXPANSION_MAX_TOKENS,
                            stream_callback=stream_callback,
                            section="insight_markdown",
                            start_accumulated=current_accumulated,
                        ),
                        timeout=160,
                    )
                    current_accumulated = max(current_accumulated, int(streamed_chars or 0))
                else:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            chat,
                            messages,
                            temperature=0.15,
                            timeout=110,
                            max_tokens=_REPORT_EXPANSION_MAX_TOKENS,
                        ),
                        timeout=135,
                    )
                    raw_chunk = str(response.choices[0].message.content or "").strip()
                chunk = self._normalize_report_expansion_chunk(raw_chunk)
                if not chunk:
                    break
                current_markdown = self._append_report_expansion(current_markdown, chunk)
            except Exception:  # noqa: BLE001
                break
        return current_markdown, current_accumulated

    def _expand_markdown_with_evidence_appendix(
        self,
        *,
        markdown: str,
        language: str,
        query: str,
        reference_catalog: list[dict[str, Any]],
        application_clusters: list[dict[str, Any]],
        role_signals: list[str],
        innovation_points: list[str],
    ) -> str:
        safe_language = "zh" if str(language or "").strip().lower() == "zh" else "en"
        enriched = self._ensure_reference_section(
            markdown=markdown,
            reference_catalog=reference_catalog,
            language=safe_language,
        )
        min_chars, _target_chars = self._resolve_report_length_targets(safe_language)
        current_chars = self._report_body_char_count(enriched)
        if current_chars >= min_chars:
            return enriched

        appendix_lines: list[str] = []
        if safe_language == "zh":
            appendix_lines.extend(
                [
                    "## 附录A. 逐篇证据卡片与方法边界",
                    f"本附录面向“{query}”提供逐篇证据拆解，强调可复现实验与适用边界判断。",
                ]
            )
        else:
            appendix_lines.extend(
                [
                    "## Appendix A. Paper-by-Paper Evidence Cards and Method Boundaries",
                    f"This appendix expands paper-level evidence for \"{query}\", emphasizing reproducibility and scope boundaries.",
                ]
            )

        for item in reference_catalog[:24]:
            if not isinstance(item, dict):
                continue
            ref_id = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not ref_id or not title:
                continue
            year = int(item.get("year") or 0)
            venue = str(item.get("venue") or "Unknown").strip() or "Unknown"
            citations = int(item.get("citations") or 0)
            abstract_hint = str(item.get("abstract_hint") or "").strip()
            if safe_language == "zh":
                appendix_lines.extend(
                    [
                        f"### [{ref_id}] {title}",
                        (
                            f"该研究发表于 {year or '年份未知'} 年，来源为 {venue}，当前引用约 {citations}。"
                            f"其核心贡献可概括为：{abstract_hint or '提出了可迁移的机制与训练范式。'}"
                        ),
                        (
                            f"机制定位：[{ref_id}] 在模型结构、训练目标或推理链路中给出关键改进，"
                            "可作为后续方案设计的基线组件。"
                        ),
                        (
                            f"适用边界：[{ref_id}] 的结论需要在任务类型、数据分布与算力预算三方面复核，"
                            "并通过对照实验验证其稳健性。"
                        ),
                        (
                            f"验证建议：以 [{ref_id}] 为对照组，增设至少一组消融实验与一组跨域迁移实验，"
                            "同时报告质量、时延、成本三类指标。"
                        ),
                    ]
                )
            else:
                appendix_lines.extend(
                    [
                        f"### [{ref_id}] {title}",
                        (
                            f"This study was published in {year or 'an unknown year'} at {venue}, with about {citations} citations. "
                            f"Its core contribution can be summarized as: {abstract_hint or 'a transferable mechanism and training paradigm.'}"
                        ),
                        (
                            f"Mechanistic role: [{ref_id}] introduces key upgrades in architecture, training objective, or reasoning pathway, "
                            "and can serve as a baseline component for downstream system design."
                        ),
                        (
                            f"Boundary conditions: findings from [{ref_id}] should be re-validated under task type, data distribution, and compute budget constraints."
                        ),
                        (
                            f"Validation plan: use [{ref_id}] as a control baseline with one ablation group and one cross-domain transfer group, "
                            "reporting quality, latency, and cost metrics."
                        ),
                    ]
                )

        if safe_language == "zh":
            appendix_lines.append("## 附录B. 分层评估清单与执行建议")
            for cluster in application_clusters[:8]:
                name = str(cluster.get("name") or "应用方向").strip() or "应用方向"
                signals = cluster.get("signals") or []
                signal_text = "、".join([str(item).strip() for item in signals if str(item).strip()][:4]) or "暂无显式信号"
                appendix_lines.append(
                    f"- {name}：优先围绕“{signal_text}”构建分层评测集，分别验证离线准确性、在线稳定性与单位成本。"
                )
            if role_signals:
                appendix_lines.append("### 关键分析信号补充")
                for line in role_signals[:16]:
                    appendix_lines.append(f"- {line}")
            if innovation_points:
                appendix_lines.append("### 创新议题补充")
                for line in innovation_points[:10]:
                    appendix_lines.append(f"- {line}")
        else:
            appendix_lines.append("## Appendix B. Layered Evaluation Checklist and Execution Notes")
            for cluster in application_clusters[:8]:
                name = str(cluster.get("name") or "application direction").strip() or "application direction"
                signals = cluster.get("signals") or []
                signal_text = ", ".join([str(item).strip() for item in signals if str(item).strip()][:4]) or "no explicit signal"
                appendix_lines.append(
                    f"- {name}: build layered benchmarks around \"{signal_text}\", and evaluate offline quality, online stability, and unit economics."
                )
            if role_signals:
                appendix_lines.append("### Additional Analytical Signals")
                for line in role_signals[:16]:
                    appendix_lines.append(f"- {line}")
            if innovation_points:
                appendix_lines.append("### Additional Innovation Threads")
                for line in innovation_points[:10]:
                    appendix_lines.append(f"- {line}")

        expanded = self._append_report_expansion(enriched, "\n".join(appendix_lines))
        if self._report_body_char_count(expanded) >= min_chars:
            return expanded

        # If still short, add a deterministic evidence matrix stub for the top references.
        matrix_lines: list[str] = []
        if safe_language == "zh":
            matrix_lines.append("## 附录C. 证据矩阵（扩展版）")
            for item in reference_catalog[:24]:
                ref_id = str(item.get("id") or "").strip()
                title = str(item.get("title") or "").strip()
                if not ref_id or not title:
                    continue
                matrix_lines.extend(
                    [
                        f"### [{ref_id}] 证据矩阵条目",
                        f"[{ref_id}] 对“{query}”的直接支持维度包括：理论机制解释、工程可实现性、跨场景迁移潜力。",
                        f"[{ref_id}] 的潜在争议点包括：实验设置是否充分、评测口径是否一致、成本收益是否平衡。",
                        f"[{ref_id}] 建议纳入统一评测协议：同数据切分、同预算约束、同误差容忍阈值下进行横向比较。",
                    ]
                )
        else:
            matrix_lines.append("## Appendix C. Extended Evidence Matrix")
            for item in reference_catalog[:24]:
                ref_id = str(item.get("id") or "").strip()
                title = str(item.get("title") or "").strip()
                if not ref_id or not title:
                    continue
                matrix_lines.extend(
                    [
                        f"### [{ref_id}] Evidence Matrix Entry",
                        f"[{ref_id}] contributes direct evidence for \"{query}\" in mechanistic interpretation, engineering feasibility, and transfer potential.",
                        f"[{ref_id}] requires scrutiny on experimental sufficiency, metric comparability, and cost-benefit realism.",
                        f"[{ref_id}] should be evaluated under a unified protocol with matched data splits, budgets, and tolerance thresholds.",
                    ]
                )
        return self._append_report_expansion(expanded, "\n".join(matrix_lines))

    def _compose_markdown_fallback(
        self,
        *,
        language: str,
        query: str,
        graph_stats: dict[str, int],
        all_paper_count: int,
        founder_primary: dict[str, Any] | None,
        founder_candidates: list[dict[str, Any]],
        timeline_papers: list[dict[str, Any]],
        role_signals: list[str],
        application_clusters: list[dict[str, Any]],
        innovation_points: list[str],
        critic_notes: list[str],
        reference_catalog: list[dict[str, Any]],
    ) -> str:
        ref_lookup = {
            self._paper_title_key(str(item.get("title") or "")): str(item.get("id") or "").strip()
            for item in reference_catalog
        }

        def _ref_marker(item: dict[str, Any] | None) -> str:
            if not isinstance(item, dict):
                return ""
            key = self._paper_title_key(str(item.get("title") or ""))
            ref_id = ref_lookup.get(key, "")
            return f"[{ref_id}]" if ref_id else ""

        if language == "zh":
            sections = [
                f"# 研究洞察报告：{query}",
                "",
                "## 摘要",
                (
                    f"本报告基于当前检索到的 {all_paper_count} 篇论文及知识图谱证据（节点 {graph_stats['node_count']}、"
                    f"关系 {graph_stats['edge_count']}）进行归纳。结论聚焦于研究起源、关键机制、应用落地与可执行创新方向，"
                    "并在证据不足处显式标注不确定性。"
                ),
                "",
                "## 1. 研究起源与关键演进",
            ]
            if founder_primary is not None:
                marker = _ref_marker(founder_primary)
                marker_text = f" {marker}" if marker else ""
                sections.append(
                    (
                        f"在当前高相关样本中，{self._format_paper_reference_line(founder_primary, language='zh')}"
                        f"{marker_text} 可作为“起点候选”进行追踪。该候选仅代表当前样本内的最优证据，不构成领域唯一结论。"
                    )
                )
            else:
                sections.append("当前证据不足以锁定单一鼻祖论文，需补充早期论文与后续引用链数据。")
            if founder_candidates:
                sections.append("候选起源证据：")
                for item in founder_candidates:
                    marker = _ref_marker(item)
                    prefix = f"{marker} " if marker else ""
                    sections.append(f"- {prefix}{self._format_paper_reference_line(item, language='zh')}")
            if timeline_papers:
                sections.append("关键演进节点：")
                for item in timeline_papers[:8]:
                    marker = _ref_marker(item)
                    prefix = f"{marker} " if marker else ""
                    sections.append(f"- {prefix}{self._format_paper_reference_line(item, language='zh')}")

            sections.extend(
                [
                    "",
                    "## 2. 关键证据与机制分析",
                ]
            )
            if role_signals:
                for line in role_signals[:8]:
                    sections.append(f"- {line}")
            else:
                sections.append("- 当前证据不足以支持细粒度机制分析，建议补充可复现实验与对照结果。")

            sections.extend(
                [
                    "",
                    "## 3. 应用落地与产业化进展",
                ]
            )
            if application_clusters:
                for cluster in application_clusters[:5]:
                    sections.append(f"- 场景：{str(cluster.get('name') or '通用场景')}")
                    for evidence in list(cluster.get("evidence") or [])[:3]:
                        sections.append(f"  证据：{evidence}")
            else:
                sections.append("- 当前样本尚未形成稳定的应用簇，产业化路径仍待验证。")

            sections.extend(
                [
                    "",
                    "## 4. 创新机会与研究议程",
                ]
            )
            if innovation_points:
                for point in innovation_points[:6]:
                    sections.append(f"- {point}")
            else:
                sections.extend(
                    [
                        "- 构建统一评测基线（效果、成本、稳定性三维）并形成公开可复现协议。",
                        "- 强化跨场景迁移能力，降低新场景部署的微调与数据成本。",
                        "- 将结构化知识约束引入生成流程，以降低关键任务中的幻觉风险。",
                    ]
                )

            sections.extend(
                [
                    "",
                    "## 5. 局限性与风险",
                ]
            )
            if critic_notes:
                for note in critic_notes[:5]:
                    sections.append(f"- {note}")
            else:
                sections.append("- 当前证据覆盖仍偏窄，结论对数据集与评测协议具有依赖性。")

            sections.extend(
                [
                    "",
                    "## 6. 结论",
                    (
                        "现有证据支持该方向已进入“方法演进 + 场景渗透”的阶段，"
                        "下一步增量价值取决于严格评测闭环、可复现证据链和工程化成本控制。"
                    ),
                    "",
                    "## 参考文献",
                ]
            )
            if reference_catalog:
                for item in reference_catalog[:20]:
                    sections.append(
                        f"- [{item['id']}] {item['title']}（{item['year'] or '年份未知'}，{item['venue']}，引用 {item['citations']}）"
                    )
            else:
                sections.append("- 当前样本中无可用参考文献条目。")
            return "\n".join(sections).strip() + "\n"

        sections = [
            f"# Research Insight Report: {query}",
            "",
            "## Abstract",
            (
                f"This report synthesizes {all_paper_count} retrieved papers and graph evidence "
                f"({graph_stats['node_count']} nodes, {graph_stats['edge_count']} relations). "
                "It focuses on origin, mechanism-level findings, adoption status, and executable innovation directions, "
                "while explicitly stating uncertainty where evidence is insufficient."
            ),
            "",
            "## 1. Research Origin and Evolution",
        ]
        if founder_primary is not None:
            marker = _ref_marker(founder_primary)
            marker_text = f" {marker}" if marker else ""
            sections.append(
                (
                    f"Within the highest-relevance sample, {self._format_paper_reference_line(founder_primary, language='en')}"
                    f"{marker_text} is treated as a leading origin candidate. This is a best-fit inference inside the current sample, "
                    "not a universal historical claim."
                )
            )
        else:
            sections.append("Current evidence is insufficient to identify a single seminal paper with confidence.")
        if founder_candidates:
            sections.append("Origin candidates:")
            for item in founder_candidates:
                marker = _ref_marker(item)
                prefix = f"{marker} " if marker else ""
                sections.append(f"- {prefix}{self._format_paper_reference_line(item, language='en')}")
        if timeline_papers:
            sections.append("Key evolution milestones:")
            for item in timeline_papers[:8]:
                marker = _ref_marker(item)
                prefix = f"{marker} " if marker else ""
                sections.append(f"- {prefix}{self._format_paper_reference_line(item, language='en')}")

        sections.extend(
            [
                "",
                "## 2. Evidence-Based Findings and Mechanisms",
            ]
        )
        if role_signals:
            for line in role_signals[:8]:
                sections.append(f"- {line}")
        else:
            sections.append("- Current evidence is insufficient for robust mechanism-level synthesis.")

        sections.extend(
            [
                "",
                "## 3. Applications and Industrial Adoption",
            ]
        )
        if application_clusters:
            for cluster in application_clusters[:5]:
                sections.append(f"- Scenario: {str(cluster.get('name') or 'General scenario')}")
                for evidence in list(cluster.get("evidence") or [])[:3]:
                    sections.append(f"  Evidence: {evidence}")
        else:
            sections.append("- No stable application cluster can be inferred from the current sample.")

        sections.extend(
            [
                "",
                "## 4. Innovation Opportunities and Research Agenda",
            ]
        )
        if innovation_points:
            for point in innovation_points[:6]:
                sections.append(f"- {point}")
        else:
            sections.extend(
                [
                    "- Build a unified evaluation baseline across quality, latency, and cost.",
                    "- Improve cross-domain transfer to reduce adaptation cost per new scenario.",
                    "- Integrate structured knowledge constraints to reduce hallucination risk in critical tasks.",
                ]
            )

        sections.extend(
            [
                "",
                "## 5. Limitations and Risks",
            ]
        )
        if critic_notes:
            for note in critic_notes[:5]:
                sections.append(f"- {note}")
        else:
            sections.append("- Current evidence coverage is limited, and conclusions are sensitive to evaluation setup.")

        sections.extend(
            [
                "",
                "## 6. Conclusion",
                (
                    "The evidence indicates a transition from capability growth to deployment-driven value creation. "
                    "The next impact frontier depends on reproducible evaluation loops, stronger evidence traceability, and lower deployment cost."
                ),
                "",
                "## References",
            ]
        )
        if reference_catalog:
            for item in reference_catalog[:20]:
                sections.append(
                    f"- [{item['id']}] {item['title']} ({item['year'] or 'year unknown'}, {item['venue']}, citations {item['citations']})"
                )
        else:
            sections.append("- No citable references are available in the current sample.")
        return "\n".join(sections).strip() + "\n"

    @staticmethod
    def _paper_title_key(title: str) -> str:
        safe = re.sub(r"\s+", " ", str(title or "").strip().lower())
        return safe

    @staticmethod
    def _extract_query_terms(query: str) -> list[str]:
        safe_query = re.sub(r"\s+", " ", str(query or "").strip().lower())
        if not safe_query:
            return []
        english_terms = re.findall(r"[a-z0-9][a-z0-9\-]{2,}", safe_query)
        cjk_terms = [item for item in re.findall(r"[\u4e00-\u9fff]{2,}", safe_query) if len(item) >= 2]
        terms: list[str] = []
        seen: set[str] = set()
        for token in [safe_query, *english_terms, *cjk_terms]:
            normalized = str(token or "").strip()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
            if len(terms) >= 12:
                break
        return terms

    def _rank_papers_by_query_relevance(
        self,
        papers: list[dict[str, Any]],
        *,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        terms = self._extract_query_terms(query)
        if not terms:
            return self._top_papers_for_prompt(papers, limit=max(1, int(limit)))
        full_phrase = terms[0]
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in papers:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            abstract = str(item.get("abstract") or "").strip()
            if not title and not abstract:
                continue
            title_lc = title.lower()
            abstract_lc = abstract.lower()
            score = 0.0
            if full_phrase and full_phrase in title_lc:
                score += 10.0
            elif full_phrase and full_phrase in abstract_lc:
                score += 6.0
            for token in terms[1:]:
                if token in title_lc:
                    score += 3.6
                elif token in abstract_lc:
                    score += 1.8
            citations = self._safe_int(item.get("citation_count"), 0)
            year = self._safe_int(item.get("year"), 0)
            score += min(8.0, float(max(0, citations)) / 900.0)
            if year >= 2020:
                score += 1.2
            elif year >= 2016:
                score += 0.7
            scored.append((score, dict(item)))
        scored.sort(
            key=lambda pair: (
                pair[0],
                self._safe_int(pair[1].get("citation_count"), 0),
                self._safe_int(pair[1].get("year"), 0),
            ),
            reverse=True,
        )
        return [item for _, item in scored[: max(1, int(limit))]]

    def _build_reference_catalog(
        self,
        papers: list[dict[str, Any]],
        *,
        language: str,
    ) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for index, item in enumerate(papers, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            year = self._safe_int(item.get("year"), 0)
            citations = self._safe_int(item.get("citation_count"), 0)
            venue = str(item.get("venue") or "Unknown").strip() or "Unknown"
            catalog.append(
                {
                    "id": f"R{index}",
                    "title": title,
                    "year": year,
                    "venue": venue,
                    "citations": citations,
                    "abstract_hint": self._summarize_abstract_text(
                        item.get("abstract"),
                        max_chars=180 if language == "zh" else 220,
                    ),
                }
            )
        return catalog

    def _clean_report_markdown(self, markdown: str, *, language: str) -> str:
        safe = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not safe:
            return ""
        noise_patterns = [
            r"\bsub[- ]?agent(s)?\b",
            r"\bagent(s)?\b",
            r"\bworkflow\b",
            r"\borchestrat(e|ed|ion)\b",
            r"\btool call(s)?\b",
            r"子代理",
            r"智能体",
            r"工作流",
            r"协同轮次",
            r"工具调用",
        ]
        deduped_lines: list[str] = []
        seen: set[str] = set()
        blank_streak = 0
        for raw_line in safe.split("\n"):
            line = str(raw_line or "").rstrip()
            stripped = line.strip()
            if stripped:
                lower = stripped.lower()
                if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in noise_patterns):
                    continue
                normalized_key = re.sub(r"\s+", " ", stripped).strip().lower()
                if normalized_key in seen:
                    continue
                seen.add(normalized_key)
                deduped_lines.append(stripped)
                blank_streak = 0
                continue
            blank_streak += 1
            if blank_streak <= 1:
                deduped_lines.append("")

        cleaned = "\n".join(deduped_lines).strip()
        if not cleaned:
            return ""
        if language == "zh" and not cleaned.startswith("# "):
            cleaned = f"# 研究洞察报告\n\n{cleaned}"
        if language == "en" and not cleaned.startswith("# "):
            cleaned = f"# Research Insight Report\n\n{cleaned}"
        return cleaned

    @staticmethod
    def _normalize_streamed_report_markdown(markdown: str, *, language: str) -> str:
        safe = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not safe:
            return ""
        if language == "zh" and not safe.startswith("# "):
            safe = f"# 研究洞察报告\n\n{safe}"
        if language == "en" and not safe.startswith("# "):
            safe = f"# Research Insight Report\n\n{safe}"
        return safe

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
            r"\bexploration completed\b",
            r"\btask completed\b",
            r"\binsight orchestrator\b",
            r"第\s*\d+\s*轮",
            r"任务完成",
            r"已完成",
            r"正在实时生成报告内容",
            r"子代理",
            r"多智能体",
            r"智能体",
            r"工作流",
            r"协商",
            r"工具调用",
            r"<\/?scp>",
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

    async def _emit_stream_done(
        self,
        *,
        callback: StreamCallback,
        section: str,
        accumulated_chars: int,
    ) -> None:
        try:
            await callback(
                {
                    "section": str(section or "insight_markdown"),
                    "chunk": "",
                    "accumulated_chars": max(0, int(accumulated_chars or 0)),
                    "done": True,
                }
            )
        except Exception:  # noqa: BLE001
            pass

    async def _stream_chat_completion_content(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        timeout_seconds: float,
        max_tokens: int | None,
        stream_callback: StreamCallback,
        section: str,
        start_accumulated: int = 0,
    ) -> tuple[str, int]:
        loop = asyncio.get_running_loop()
        safe_section = str(section or "insight_markdown").strip().lower() or "insight_markdown"
        safe_timeout = max(10.0, float(timeout_seconds or 10.0))
        initial_accumulated = max(0, int(start_accumulated or 0))
        safe_max_tokens = int(max_tokens or 0)

        def _producer() -> tuple[str, int]:
            pieces: list[str] = []
            accumulated = initial_accumulated
            try:
                client = get_client()
                request_payload: dict[str, Any] = {
                    "model": str(self.settings.openai_model),
                    "messages": messages,
                    "temperature": float(temperature),
                    "timeout": safe_timeout,
                    "stream": True,
                }
                if safe_max_tokens > 0:
                    request_payload["max_tokens"] = safe_max_tokens
                stream = client.chat.completions.create(
                    **request_payload,
                )
                for event in stream:
                    delta = self._extract_stream_delta_content(event)
                    if not delta:
                        continue
                    pieces.append(delta)
                    accumulated += len(delta)
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            stream_callback(
                                {
                                    "section": safe_section,
                                    "chunk": delta,
                                    "accumulated_chars": accumulated,
                                    "done": False,
                                }
                            ),
                            loop,
                        )
                        future.result(timeout=5.0)
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                pass
            return ("".join(pieces), accumulated)

        return await asyncio.to_thread(_producer)

    @staticmethod
    def _extract_stream_delta_content(chunk: Any) -> str:
        try:
            choices = getattr(chunk, "choices", None)
            if not choices:
                return ""
            first_choice = choices[0]
            delta = getattr(first_choice, "delta", None)
            if delta is None:
                return ""
            content = getattr(delta, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str) and text:
                            parts.append(text)
                return "".join(parts)
        except Exception:  # noqa: BLE001
            return ""
        return ""

    async def _emit_lifecycle_event(
        self,
        *,
        stream_callback: StreamCallback | None,
        session_id: str,
        event_type: str,
        stage_started_at: float | None = None,
        accumulated_chars: int = 0,
        level: str = "info",
        details: dict[str, Any] | None = None,
    ) -> None:
        if stream_callback is None:
            return
        safe_event_type = str(event_type or "").strip().lower()
        if not safe_event_type:
            return
        payload: dict[str, Any] = {
            "type": safe_event_type,
            "session_id": str(session_id or "").strip(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": 0,
        }
        if stage_started_at is not None:
            payload["elapsed_ms"] = max(0, int((perf_counter() - float(stage_started_at)) * 1000))
        safe_level = str(level or "").strip().lower()
        if safe_level in {"warning", "error"}:
            payload["level"] = safe_level
        for key, value in dict(details or {}).items():
            safe_key = str(key or "").strip()
            if not safe_key:
                continue
            payload[safe_key] = value
        try:
            await stream_callback(
                {
                    "section": "insight_orchestrator_event",
                    "event": payload,
                    "chunk": "",
                    "accumulated_chars": max(0, int(accumulated_chars or 0)),
                    "done": False,
                }
            )
        except Exception:  # noqa: BLE001
            # Lifecycle telemetry should not block report generation.
            pass

    def _persist_artifacts(self, *, session_id: str, markdown: str, language: str) -> dict[str, str]:
        md_path = self._persist_markdown_artifact(
            session_id=session_id,
            markdown=markdown,
        )
        pdf_path = ""
        try:
            pdf_path = self._persist_pdf_artifact(
                markdown=markdown,
                markdown_path=md_path,
                language=language,
            )
        except Exception:  # noqa: BLE001
            pdf_path = ""
        return {
            "markdown_path": str(md_path or ""),
            "pdf_path": str(pdf_path or ""),
        }

    def _persist_markdown_artifact(self, *, session_id: str, markdown: str) -> str:
        output_dir = self.report_root / str(session_id or "").strip()
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "insight.md"
        md_path.write_text(str(markdown or ""), encoding="utf-8")
        return str(md_path)

    def _persist_pdf_artifact(
        self,
        *,
        markdown: str,
        markdown_path: str,
        language: str,
    ) -> str:
        if not _REPORTLAB_AVAILABLE:
            return ""
        md_path = Path(str(markdown_path or "").strip())
        if not md_path.parent.exists():
            md_path.parent.mkdir(parents=True, exist_ok=True)
        target_pdf_path = md_path.parent / "insight.pdf"
        rendered_path = self.render_markdown_pdf(
            markdown=markdown,
            pdf_path=target_pdf_path,
            language=language,
        )
        return str(rendered_path) if str(rendered_path).strip() else ""

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
