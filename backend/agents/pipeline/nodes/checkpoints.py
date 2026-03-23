from __future__ import annotations

import json

from agents.pipeline.nodes.utils import deduplicate_keywords, extract_keywords_from_text
from agents.pipeline.state import PipelineState, append_message
from services.pipeline_runtime_service import get_pipeline_runtime_service

_DEFAULT_AGENT_COUNT = 4
_DEFAULT_EXPLORATION_DEPTH = 2
_MIN_AGENT_COUNT = 2
_MAX_AGENT_COUNT = 8
_MIN_EXPLORATION_DEPTH = 1
_MAX_EXPLORATION_DEPTH = 5


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


def _clamp_int(value: object, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _resolve_insight_config(feedback: str, state: PipelineState) -> dict[str, int]:
    baseline = state.get("insight_config") or {}
    payload: dict[str, object] = {}
    safe_feedback = str(feedback or "").strip()
    if safe_feedback:
        try:
            parsed = json.loads(safe_feedback)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}

    return {
        "agent_count": _clamp_int(
            payload.get("agent_count", baseline.get("agent_count", _DEFAULT_AGENT_COUNT)),
            default=_DEFAULT_AGENT_COUNT,
            min_value=_MIN_AGENT_COUNT,
            max_value=_MAX_AGENT_COUNT,
        ),
        "exploration_depth": _clamp_int(
            payload.get("exploration_depth", baseline.get("exploration_depth", _DEFAULT_EXPLORATION_DEPTH)),
            default=_DEFAULT_EXPLORATION_DEPTH,
            min_value=_MIN_EXPLORATION_DEPTH,
            max_value=_MAX_EXPLORATION_DEPTH,
        ),
    }


async def human_checkpoint_2(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]
    node = "checkpoint_2"

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, node, 78)

    message = (
        "知识图谱已生成。请确认探索参数后继续："
        "agent_count（2-8）与 exploration_depth（1-5）。"
    )
    feedback = await runtime.wait_for_checkpoint(
        session_id,
        checkpoint=node,
        message=message,
        timeout_seconds=None,
    )

    config = _resolve_insight_config(feedback, state)
    summary = (
        "探索参数已确认："
        f"{config['agent_count']} 个 Agents，探索深度 {config['exploration_depth']}。"
    )
    await runtime.emit_thinking(session_id, node, summary)
    await runtime.emit_node_complete(session_id, node, 80, summary)

    return {
        **state,
        "insight_config": config,
        "should_pause": False,
        "current_node": node,
        "progress": 80,
        "messages": append_message(state, summary),
    }
