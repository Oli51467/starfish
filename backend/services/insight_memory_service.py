from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from services.insight_agent_contracts import AgentMemoryWriteRecord


class InsightMemoryService:
    """Isolated memory manager for session-shared, agent-private and history scopes."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}

    def initialize_run(self, *, run_id: str, history_memory: list[str] | None = None) -> None:
        safe_run_id = str(run_id or "").strip()
        if not safe_run_id:
            return
        self._runs[safe_run_id] = {
            "session_shared": defaultdict(list),
            "agent_private": defaultdict(lambda: defaultdict(list)),
            "history_shared": [str(item) for item in (history_memory or []) if str(item).strip()],
        }

    def write(self, *, run_id: str, record: AgentMemoryWriteRecord) -> None:
        state = self._runs.get(str(run_id or "").strip())
        if state is None:
            return
        key = str(record.key or "").strip()
        value = str(record.value or "").strip()
        if not key or not value:
            return

        if record.scope == "session_shared":
            state["session_shared"][key].append(value)
            return

        if record.scope == "agent_private":
            profile_id = str(record.profile_id or "").strip()
            if not profile_id:
                return
            state["agent_private"][profile_id][key].append(value)
            return

        if record.scope == "history_shared":
            state["history_shared"].append(value)

    def write_many(self, *, run_id: str, records: list[AgentMemoryWriteRecord]) -> None:
        for item in records or []:
            if not isinstance(item, AgentMemoryWriteRecord):
                continue
            self.write(run_id=run_id, record=item)

    def read_session(self, *, run_id: str, key: str, limit: int = 8) -> list[str]:
        state = self._runs.get(str(run_id or "").strip())
        if state is None:
            return []
        items = list((state["session_shared"].get(str(key or "").strip()) or []))
        safe_limit = max(1, int(limit))
        return items[-safe_limit:]

    def read_agent(self, *, run_id: str, profile_id: str, key: str, limit: int = 4) -> list[str]:
        state = self._runs.get(str(run_id or "").strip())
        if state is None:
            return []
        safe_profile_id = str(profile_id or "").strip()
        if not safe_profile_id:
            return []
        agent_memory = state["agent_private"].get(safe_profile_id) or {}
        items = list((agent_memory.get(str(key or "").strip()) or []))
        safe_limit = max(1, int(limit))
        return items[-safe_limit:]

    def read_history(self, *, run_id: str, limit: int = 4) -> list[str]:
        state = self._runs.get(str(run_id or "").strip())
        if state is None:
            return []
        items = list(state.get("history_shared") or [])
        safe_limit = max(1, int(limit))
        return items[-safe_limit:]

    def build_session_view(self, *, run_id: str) -> dict[str, list[str]]:
        return {
            "hypotheses": self.read_session(run_id=run_id, key="hypotheses", limit=12),
            "evidence": self.read_session(run_id=run_id, key="evidence", limit=16),
            "decisions": self.read_session(run_id=run_id, key="decisions", limit=16),
            "critic_notes": self.read_session(run_id=run_id, key="critic_notes", limit=12),
        }

    def snapshot(self, *, run_id: str) -> dict[str, Any]:
        state = self._runs.get(str(run_id or "").strip())
        if state is None:
            return {
                "session_shared": {},
                "agent_private": {},
                "history_shared": [],
            }
        return {
            "session_shared": {
                key: list(values)
                for key, values in dict(state.get("session_shared") or {}).items()
            },
            "agent_private": {
                profile_id: {
                    key: list(values)
                    for key, values in dict(agent_map).items()
                }
                for profile_id, agent_map in dict(state.get("agent_private") or {}).items()
            },
            "history_shared": list(state.get("history_shared") or []),
        }

    def clear_run(self, *, run_id: str) -> None:
        self._runs.pop(str(run_id or "").strip(), None)

    def clone_session_view(self, *, run_id: str) -> dict[str, list[str]]:
        return deepcopy(self.build_session_view(run_id=run_id))
