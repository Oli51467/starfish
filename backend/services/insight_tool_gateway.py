from __future__ import annotations

from time import perf_counter
from typing import Any

from services.insight_agent_contracts import AgentProfile, AgentToolCallRecord


class InsightToolGateway:
    """Permission-aware tool gateway for insight agents."""

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
            if safe_tool == "graph_stats":
                payload = dict(context.get("graph_stats") or {})
            elif safe_tool == "paper_catalog":
                papers = list(context.get("papers") or [])
                payload = [
                    {
                        "paper_id": str(item.get("paper_id") or ""),
                        "title": str(item.get("title") or ""),
                        "year": int(item.get("year") or 0),
                        "citation_count": int(item.get("citation_count") or 0),
                    }
                    for item in papers[:8]
                    if isinstance(item, dict)
                ]
            elif safe_tool == "history_memory":
                payload = [str(item) for item in (context.get("history_memory") or []) if str(item).strip()][:4]
            elif safe_tool == "expansion_retrieval":
                payload = [
                    {
                        "paper_id": str(item.get("paper_id") or ""),
                        "title": str(item.get("title") or ""),
                        "year": int(item.get("year") or 0),
                    }
                    for item in (context.get("extension_papers") or [])[:6]
                    if isinstance(item, dict)
                ]
            elif safe_tool == "llm":
                payload = {"enabled": bool(context.get("llm_enabled", True))}
            else:
                payload = None
                status = "unsupported"
                detail = "unknown_tool"
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
