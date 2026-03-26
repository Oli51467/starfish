from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable

from services.insight_agent_contracts import AgentProfile, AgentToolCallRecord
from services.insight_tool_gateway import InsightToolGateway

SkillExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Any]


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    required_tools: tuple[str, ...] = ()
    memory_scope: str = "session_shared"
    memory_key: str = ""
    share_with_subagents: bool = True
    executor: SkillExecutor | None = None

    def resolved_memory_key(self) -> str:
        safe = str(self.memory_key or "").strip()
        if safe:
            return safe
        return f"skill::{self.skill_id}::output"


@dataclass
class SkillExecutionResult:
    skill_id: str
    status: str
    output: Any = None
    detail: str = ""
    tool_calls: list[AgentToolCallRecord] = field(default_factory=list)
    tool_payloads: dict[str, Any] = field(default_factory=dict)


class InsightSkillRegistry:
    """Skill planner and executor for insight orchestrated agents."""

    _DEFAULT_SKILL_KEYWORDS: dict[str, tuple[str, ...]] = {
        "trend_analysis": ("trend", "state", "现状", "趋势"),
        "evidence_synthesis": ("evidence", "证据", "synthesis", "综合"),
        "citation_graph_reasoning": ("citation", "graph", "关系", "图谱"),
        "cluster_mapping": ("cluster", "mapping", "聚类", "结构"),
        "architecture_design": ("architecture", "架构", "设计"),
        "constraint_tradeoff": ("constraint", "tradeoff", "约束", "权衡"),
        "scenario_design": ("scenario", "application", "场景", "应用"),
        "value_hypothesis": ("value", "hypothesis", "价值", "假设"),
        "expansion_retrieval": ("expand", "retrieval", "扩展", "检索"),
        "evidence_validation": ("validation", "verify", "核验", "验证"),
        "execution_planning": ("plan", "milestone", "执行", "里程碑"),
        "milestone_estimation": ("estimate", "timeline", "估算", "周期"),
        "risk_modeling": ("risk", "failure", "风险", "失败"),
        "assumption_audit": ("assumption", "audit", "假设", "审计"),
        "multi_view_synthesis": ("synthesis", "cross", "综合", "多视角"),
        "report_composition": ("report", "compose", "报告", "写作"),
        "general_analysis": ("analysis", "分析"),
    }

    def __init__(self) -> None:
        self._skills: dict[str, SkillSpec] = {}
        self._register_defaults()

    def register(self, spec: SkillSpec) -> None:
        safe_skill_id = str(spec.skill_id or "").strip()
        if not safe_skill_id:
            return
        self._skills[safe_skill_id] = SkillSpec(
            skill_id=safe_skill_id,
            required_tools=tuple(
                item for item in (spec.required_tools or ()) if str(item).strip()
            ),
            memory_scope=str(spec.memory_scope or "session_shared").strip() or "session_shared",
            memory_key=str(spec.memory_key or "").strip(),
            share_with_subagents=bool(spec.share_with_subagents),
            executor=spec.executor,
        )

    def get(self, skill_id: str) -> SkillSpec | None:
        return self._skills.get(str(skill_id or "").strip())

    def select_skills(
        self,
        *,
        profile: AgentProfile,
        objective: str,
        context: dict[str, Any],
        limit: int = 4,
    ) -> tuple[str, ...]:
        declared = [item for item in (profile.skills or ()) if self.get(item) is not None]
        if not declared:
            fallback = "general_analysis" if self.get("general_analysis") is not None else ""
            return (fallback,) if fallback else ()

        safe_limit = max(1, int(limit))
        objective_text = " ".join(
            [
                str(objective or "").strip().lower(),
                str(context.get("query") or "").strip().lower(),
                str(context.get("objective_hint") or "").strip().lower(),
            ]
        ).strip()
        objective_text = re.sub(r"\s+", " ", objective_text)
        requested = self._normalize_skill_list(context.get("selected_skills"))
        requested_set = set(requested)

        scored: list[tuple[float, int, str]] = []
        for index, skill_id in enumerate(declared):
            score = float(max(0, len(declared) - index))
            if skill_id in requested_set:
                score += 20.0
            for token in self._DEFAULT_SKILL_KEYWORDS.get(skill_id, ()):
                if token and token in objective_text:
                    score += 2.0
            scored.append((score, index, skill_id))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        return tuple(item[2] for item in scored[:safe_limit])

    def execute(
        self,
        *,
        task_id: str,
        profile: AgentProfile,
        skill_id: str,
        context: dict[str, Any],
        tool_gateway: InsightToolGateway,
    ) -> SkillExecutionResult:
        spec = self.get(skill_id)
        safe_skill_id = str(skill_id or "").strip()
        if spec is None:
            return SkillExecutionResult(
                skill_id=safe_skill_id or "unknown",
                status="unsupported",
                output=None,
                detail="skill_not_registered",
            )

        tool_payloads: dict[str, Any] = {}
        tool_calls: list[AgentToolCallRecord] = []
        for tool_name in spec.required_tools:
            payload, record = tool_gateway.invoke(
                task_id=task_id,
                profile=profile,
                tool_name=tool_name,
                context=context,
            )
            tool_calls.append(record)
            if payload is not None:
                tool_payloads[tool_name] = payload
                context[f"tool::{tool_name}"] = payload

        try:
            executor = spec.executor or self._default_executor
            output = executor(spec.skill_id, context, tool_payloads)
        except Exception as exc:  # noqa: BLE001
            return SkillExecutionResult(
                skill_id=spec.skill_id,
                status="error",
                output=None,
                detail=str(exc),
                tool_calls=tool_calls,
                tool_payloads=tool_payloads,
            )

        status = "completed"
        if output is None:
            status = "empty"
        return SkillExecutionResult(
            skill_id=spec.skill_id,
            status=status,
            output=output,
            detail="",
            tool_calls=tool_calls,
            tool_payloads=tool_payloads,
        )

    @staticmethod
    def serialize_output(value: Any, *, max_chars: int = 2400) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            safe_text = value.strip()
        else:
            try:
                safe_text = json.dumps(value, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                safe_text = str(value).strip()
        safe_text = re.sub(r"\s+", " ", safe_text).strip()
        if not safe_text:
            return ""
        safe_limit = max(256, int(max_chars))
        if len(safe_text) <= safe_limit:
            return safe_text
        return safe_text[: max(1, safe_limit - 3)].rstrip() + "..."

    @staticmethod
    def _normalize_skill_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        output: list[str] = []
        seen: set[str] = set()
        for item in value:
            safe = str(item or "").strip()
            if not safe or safe in seen:
                continue
            seen.add(safe)
            output.append(safe)
        return output

    def _register_defaults(self) -> None:
        self.register(SkillSpec("trend_analysis", ("graph_stats", "paper_catalog")))
        self.register(SkillSpec("evidence_synthesis", ("paper_catalog", "history_memory")))
        self.register(SkillSpec("citation_graph_reasoning", ("graph_stats", "paper_catalog")))
        self.register(SkillSpec("cluster_mapping", ("graph_stats", "paper_catalog")))
        self.register(SkillSpec("architecture_design", ("paper_catalog", "history_memory")))
        self.register(SkillSpec("constraint_tradeoff", ("paper_catalog", "history_memory")))
        self.register(SkillSpec("scenario_design", ("paper_catalog",)))
        self.register(SkillSpec("value_hypothesis", ("paper_catalog",)))
        self.register(SkillSpec("expansion_retrieval", ("expansion_retrieval", "paper_catalog")))
        self.register(SkillSpec("evidence_validation", ("paper_catalog", "history_memory")))
        self.register(SkillSpec("execution_planning", ("history_memory", "paper_catalog")))
        self.register(SkillSpec("milestone_estimation", ("history_memory", "paper_catalog")))
        self.register(SkillSpec("risk_modeling", ("history_memory", "paper_catalog")))
        self.register(SkillSpec("assumption_audit", ("history_memory", "paper_catalog")))
        self.register(SkillSpec("multi_view_synthesis", ("paper_catalog", "graph_stats", "history_memory")))
        self.register(SkillSpec("report_composition", ("paper_catalog", "history_memory")))
        self.register(SkillSpec("general_analysis", ("paper_catalog", "history_memory")))

    @staticmethod
    def _default_executor(
        skill_id: str,
        context: dict[str, Any],
        tool_payloads: dict[str, Any],
    ) -> dict[str, Any]:
        safe_skill_id = str(skill_id or "").strip()
        query = str(context.get("query") or "").strip()
        objective = str(context.get("objective") or "").strip()
        graph_stats = tool_payloads.get("graph_stats")
        if not isinstance(graph_stats, dict):
            graph_stats = dict(context.get("graph_stats") or {})

        paper_catalog = tool_payloads.get("paper_catalog")
        if not isinstance(paper_catalog, list):
            paper_catalog = list(context.get("tool::paper_catalog") or [])
        history_memory = tool_payloads.get("history_memory")
        if not isinstance(history_memory, list):
            history_memory = list(context.get("history_memory") or [])
        expansion = tool_payloads.get("expansion_retrieval")
        if not isinstance(expansion, list):
            expansion = list(context.get("extension_papers") or [])

        ranked_titles = [
            {
                "paper_id": str(item.get("paper_id") or ""),
                "title": str(item.get("title") or ""),
                "year": InsightSkillRegistry._safe_int(item.get("year"), 0),
                "citation_count": InsightSkillRegistry._safe_int(item.get("citation_count"), 0),
            }
            for item in paper_catalog[:6]
            if isinstance(item, dict)
        ]

        normalized_history = [
            str(item).strip()
            for item in history_memory
            if str(item).strip()
        ][:3]

        expansion_titles = [
            {
                "paper_id": str(item.get("paper_id") or ""),
                "title": str(item.get("title") or ""),
                "year": InsightSkillRegistry._safe_int(item.get("year"), 0),
            }
            for item in expansion[:4]
            if isinstance(item, dict)
        ]

        return {
            "skill_id": safe_skill_id,
            "query": query,
            "objective": objective[:320],
            "focus_hint": safe_skill_id.replace("_", " "),
            "graph_stats": {
                "node_count": InsightSkillRegistry._safe_int(graph_stats.get("node_count"), 0),
                "edge_count": InsightSkillRegistry._safe_int(graph_stats.get("edge_count"), 0),
                "paper_node_count": InsightSkillRegistry._safe_int(graph_stats.get("paper_node_count"), 0),
            },
            "paper_signals": ranked_titles,
            "history_hints": normalized_history,
            "expansion_candidates": expansion_titles,
        }

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
