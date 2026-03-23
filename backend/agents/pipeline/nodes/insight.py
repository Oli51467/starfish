from __future__ import annotations

from datetime import datetime, timezone

from agents.pipeline.state import PipelineState, append_message
from services.insight_exploration_service import get_insight_exploration_service
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "insight"
_DEFAULT_AGENT_COUNT = 4
_DEFAULT_EXPLORATION_DEPTH = 2
_DEFAULT_AGENT_MODE = "orchestrated"


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


async def insight_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]
    config = dict(state.get("insight_config") or {})
    agent_count = max(2, min(8, _safe_int(config.get("agent_count"), _DEFAULT_AGENT_COUNT)))
    exploration_depth = max(1, min(5, _safe_int(config.get("exploration_depth"), _DEFAULT_EXPLORATION_DEPTH)))
    report_language = str(config.get("report_language") or "zh").strip().lower()
    if report_language not in {"zh", "en"}:
        report_language = "zh"
    agent_mode = str(config.get("agent_mode") or _DEFAULT_AGENT_MODE).strip().lower()
    if agent_mode not in {"legacy", "orchestrated"}:
        agent_mode = _DEFAULT_AGENT_MODE

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 82)

    service = get_insight_exploration_service()

    async def on_stream(payload: dict) -> None:
        section = str(payload.get("section") or "insight_markdown").strip().lower()
        if section == "insight_orchestrator_event":
            event_payload = payload.get("event")
            await runtime.emit_insight_orchestrator_event(
                session_id,
                event=event_payload if isinstance(event_payload, dict) else {},
            )
            return
        await runtime.emit_insight_stream(
            session_id,
            section=section or "insight_markdown",
            chunk=str(payload.get("chunk") or ""),
            accumulated_chars=int(payload.get("accumulated_chars") or 0),
            done=bool(payload.get("done")),
        )

    result = await service.generate_report(
        session_id=session_id,
        user_id=str(state.get("user_id") or "").strip(),
        query=str(state.get("input_value") or "").strip(),
        input_type=str(state.get("input_type") or "domain").strip(),
        papers=list(state.get("papers") or []),
        graph_payload=state.get("graph_payload") if isinstance(state.get("graph_payload"), dict) else None,
        agent_count=agent_count,
        exploration_depth=exploration_depth,
        preferred_language=report_language,
        agent_mode=agent_mode,
        stream_callback=on_stream,
    )

    summary = str(result.get("summary") or "").strip() or "探索与洞察已完成。"
    await runtime.emit_thinking(session_id, _NODE, summary)
    await runtime.emit_node_complete(session_id, _NODE, 98, summary)

    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
    markdown = str(result.get("markdown") or "").strip()
    resolved_mode = str(result.get("agent_mode") or agent_mode).strip().lower()
    if resolved_mode not in {"legacy", "orchestrated"}:
        resolved_mode = agent_mode
    insight_payload = {
        "status": "completed",
        "summary": summary,
        "language": str(result.get("language") or "zh"),
        "agent_count": agent_count,
        "exploration_depth": exploration_depth,
        "agent_mode": resolved_mode,
        "markdown": markdown,
        "artifact": {
            "markdown_path": str(artifact.get("markdown_path") or ""),
            "pdf_path": str(artifact.get("pdf_path") or ""),
        },
        "stats": result.get("stats") if isinstance(result.get("stats"), dict) else {},
        "memory": result.get("memory") if isinstance(result.get("memory"), dict) else {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        **state,
        "insight": insight_payload,
        "report_draft": markdown or state.get("report_draft"),
        "final_report": markdown or state.get("final_report"),
        "current_node": _NODE,
        "progress": 98,
        "messages": append_message(state, summary),
    }
