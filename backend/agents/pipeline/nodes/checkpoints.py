from __future__ import annotations

from agents.pipeline.nodes.utils import deduplicate_keywords, extract_keywords_from_text
from agents.pipeline.state import PipelineState, append_message
from services.pipeline_runtime_service import get_pipeline_runtime_service


def _is_continue_feedback(feedback: str) -> bool:
    safe = str(feedback or "").strip().lower()
    return safe in {"", "continue", "confirm", "ok", "go", "继续", "确认", "默认"}


async def human_checkpoint_1(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]
    node = "checkpoint_1"

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, node, 45)

    message = (
        f"图谱构建完成：节点 {len(state.get('graph_nodes') or [])}，"
        f"关系 {len(state.get('graph_edges') or [])}。"
        "请确认是否继续深度分析。"
    )
    feedback = await runtime.wait_for_checkpoint(
        session_id,
        checkpoint=node,
        message=message,
        timeout_seconds=30,
    )

    checkpoint_feedback = dict(state.get("checkpoint_feedback") or {})
    search_keywords = list(state.get("search_keywords") or [])

    if not _is_continue_feedback(feedback):
        checkpoint_feedback[node] = feedback
        search_keywords = deduplicate_keywords(
            search_keywords + extract_keywords_from_text(feedback, limit=4)
        )

    summary = "检查点确认完成，进入并行分析阶段。"
    await runtime.emit_node_complete(session_id, node, 45, summary)

    return {
        **state,
        "human_feedback": feedback or state.get("human_feedback"),
        "checkpoint_feedback": checkpoint_feedback,
        "search_keywords": search_keywords,
        "should_pause": False,
        "current_node": node,
        "progress": 45,
        "messages": append_message(state, summary),
    }


async def human_checkpoint_2(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]
    node = "checkpoint_2"

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, node, 90)

    message = "知识图谱已完成，请确认是否继续生成并展示血缘树。"
    feedback = await runtime.wait_for_checkpoint(
        session_id,
        checkpoint=node,
        message=message,
        timeout_seconds=0,
    )

    checkpoint_feedback = dict(state.get("checkpoint_feedback") or {})
    if not _is_continue_feedback(feedback):
        checkpoint_feedback[node] = feedback

    summary = "血缘树检查点已确认，开始生成血缘树。"
    await runtime.emit_node_complete(session_id, node, 90, summary)

    return {
        **state,
        "human_feedback": feedback if feedback is not None else state.get("human_feedback"),
        "checkpoint_feedback": checkpoint_feedback,
        "should_pause": False,
        "current_node": node,
        "progress": 90,
        "messages": append_message(state, summary),
    }
