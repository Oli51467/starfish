from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from services.insight_agent_contracts import AgentProfile, AgentToolCallRecord

ToolHandler = Callable[[dict[str, Any]], Any]


class InsightToolGateway:
    """Permission-aware tool gateway for insight agents."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._register_default_handlers()

    def register_tool(self, tool_name: str, handler: ToolHandler) -> None:
        safe_tool = str(tool_name or "").strip()
        if not safe_tool:
            return
        self._handlers[safe_tool] = handler

    def _register_default_handlers(self) -> None:
        self.register_tool("graph_stats", self._handle_graph_stats)
        self.register_tool("paper_catalog", self._handle_paper_catalog)
        self.register_tool("history_memory", self._handle_history_memory)
        self.register_tool("expansion_retrieval", self._handle_expansion_retrieval)
        self.register_tool("llm", self._handle_llm)

    @staticmethod
    def _handle_graph_stats(context: dict[str, Any]) -> dict[str, Any]:
        return dict(context.get("graph_stats") or {})

    @staticmethod
    def _handle_paper_catalog(context: dict[str, Any]) -> list[dict[str, Any]]:
        papers = list(context.get("papers") or [])
        return [
            {
                "paper_id": str(item.get("paper_id") or ""),
                "title": str(item.get("title") or ""),
                "year": int(item.get("year") or 0),
                "citation_count": int(item.get("citation_count") or 0),
            }
            for item in papers[:8]
            if isinstance(item, dict)
        ]

    @staticmethod
    def _handle_history_memory(context: dict[str, Any]) -> list[str]:
        return [str(item) for item in (context.get("history_memory") or []) if str(item).strip()][:4]

    @staticmethod
    def _handle_expansion_retrieval(context: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "paper_id": str(item.get("paper_id") or ""),
                "title": str(item.get("title") or ""),
                "year": int(item.get("year") or 0),
            }
            for item in (context.get("extension_papers") or [])[:6]
            if isinstance(item, dict)
        ]

    @staticmethod
    def _handle_llm(context: dict[str, Any]) -> dict[str, bool]:
        return {"enabled": bool(context.get("llm_enabled", True))}

    def is_allowed(self, profile: AgentProfile, tool_name: str) -> bool:
        safe_tool = str(tool_name or "").strip()
        allowed = {item for item in (profile.allowed_tools or ()) if str(item).strip()}
        return safe_tool in allowed

    def invoke(
        self,
        *,
        task_id: str,
        profile: AgentProfile,
        tool_name: str,
        context: dict[str, Any],
    ) -> tuple[Any, AgentToolCallRecord]:
        safe_tool = str(tool_name or "").strip()
        start = perf_counter()
        if not safe_tool or not self.is_allowed(profile, safe_tool):
            return None, AgentToolCallRecord(
                task_id=task_id,
                profile_id=profile.profile_id,
                tool_name=safe_tool or "unknown",
                status="denied",
                detail="tool_not_allowed",
                latency_ms=int(max(0.0, perf_counter() - start) * 1000),
            )

        payload: Any = None
        status = "ok"
        detail = ""
        try:
            handler = self._handlers.get(safe_tool)
            if handler is None:
                payload = None
                status = "unsupported"
                detail = "unknown_tool"
            else:
                payload = handler(context)
        except Exception as exc:  # noqa: BLE001
            payload = None
            status = "error"
            detail = str(exc)

        return payload, AgentToolCallRecord(
            task_id=task_id,
            profile_id=profile.profile_id,
            tool_name=safe_tool,
            status=status,
            detail=detail,
            latency_ms=int(max(0.0, perf_counter() - start) * 1000),
        )
