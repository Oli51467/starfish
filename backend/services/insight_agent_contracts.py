from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


_DEFAULT_MEMORY_SCOPE_SHARED = "session_shared"
_DEFAULT_MEMORY_SCOPE_PRIVATE = "agent_private"
_DEFAULT_MEMORY_SCOPE_HISTORY = "history_shared"


def build_task_id(prefix: str = "insight-task") -> str:
    safe_prefix = str(prefix or "insight-task").strip() or "insight-task"
    return f"{safe_prefix}-{uuid4().hex[:12]}"


@dataclass(frozen=True)
class AgentProfile:
    profile_id: str
    role_id: str
    display_name_zh: str
    display_name_en: str
    skills: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    memory_scopes: tuple[str, ...] = (
        _DEFAULT_MEMORY_SCOPE_SHARED,
        _DEFAULT_MEMORY_SCOPE_PRIVATE,
    )
    max_subagents: int = 0


@dataclass
class AgentTask:
    run_id: str
    task_id: str
    profile_id: str
    role_id: str
    round_index: int
    depth: int
    query: str
    language: str
    input_type: str
    objective: str
    parent_task_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    budget_cost: float = 0.0
    timeout_seconds: float = 25.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class SubAgentRequest:
    objective: str
    profile_id: str | None = None
    role_id: str | None = None
    context_patch: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentToolCallRecord:
    task_id: str
    profile_id: str
    tool_name: str
    status: str
    detail: str = ""
    latency_ms: int = 0


@dataclass(frozen=True)
class AgentMemoryWriteRecord:
    task_id: str
    profile_id: str
    scope: str
    key: str
    value: str


@dataclass
class AgentTaskResult:
    task_id: str
    profile_id: str
    role_id: str
    status: str
    output: str
    tool_calls: list[AgentToolCallRecord] = field(default_factory=list)
    memory_writes: list[AgentMemoryWriteRecord] = field(default_factory=list)
    subagent_requests: list[SubAgentRequest] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoundExecutionResult:
    round_index: int
    results: list[AgentTaskResult] = field(default_factory=list)
    spawned_task_count: int = 0
    total_task_count: int = 0


@dataclass
class InsightOrchestrationJournal:
    run_id: str
    rounds: list[RoundExecutionResult] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def append_event(self, event_type: str, **payload: Any) -> None:
        self.events.append(
            {
                "type": str(event_type or "").strip() or "event",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
        )


def default_memory_scopes(*, include_history: bool = True) -> tuple[str, ...]:
    if include_history:
        return (
            _DEFAULT_MEMORY_SCOPE_SHARED,
            _DEFAULT_MEMORY_SCOPE_PRIVATE,
            _DEFAULT_MEMORY_SCOPE_HISTORY,
        )
    return (
        _DEFAULT_MEMORY_SCOPE_SHARED,
        _DEFAULT_MEMORY_SCOPE_PRIVATE,
    )
