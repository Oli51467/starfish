from __future__ import annotations

from agents.pipeline.state import PipelineState, append_message
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "router"


async def router_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 12)

    input_type = str(state.get("input_type") or "domain").strip()
    branch = "domain" if input_type == "domain" else "paper"
    summary = f"已完成入口路由，当前分支：{branch}。"

    await runtime.emit_node_complete(session_id, _NODE, 12, summary)

    return {
        **state,
        "current_node": _NODE,
        "progress": 12,
        "messages": append_message(state, summary),
    }
