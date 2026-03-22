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
        f"论文检索完成：已筛选 {len(state.get('papers') or [])} 篇论文。"
        "请确认是否继续生成知识图谱。"
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

    summary = "检查点确认完成，进入知识图谱构建阶段。"
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
