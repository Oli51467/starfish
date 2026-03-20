from __future__ import annotations

import asyncio

from agents.pipeline.state import PipelineState, append_message
from core.llm_client import chat, is_configured
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "report"


def _is_effective_feedback(feedback: str) -> bool:
    safe = str(feedback or "").strip().lower()
    return safe not in {"", "continue", "confirm", "ok", "继续", "确认"}


async def _revise_with_llm(draft: str, feedback: str) -> str:
    response = await asyncio.wait_for(
        asyncio.to_thread(
            chat,
            [
                {
                    "role": "system",
                    "content": "根据用户反馈修订报告，保持章节结构，不要省略关键结论。",
                },
                {
                    "role": "user",
                    "content": f"原报告：\n{draft}\n\n用户反馈：{feedback}",
                },
            ],
            temperature=0.2,
            timeout=20,
        ),
        timeout=22,
    )
    content = ""
    try:
        content = str(response.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001
        content = ""
    return content or draft


async def report_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 94)

    draft = str(state.get("report_draft") or "").strip()
    if not draft:
        draft = "# AutoResearch Report\n\n暂无可用内容。"

    feedback = str((state.get("checkpoint_feedback") or {}).get("checkpoint_2") or state.get("human_feedback") or "").strip()
    final_report = draft

    if _is_effective_feedback(feedback):
        if is_configured():
            try:
                final_report = await _revise_with_llm(draft, feedback)
            except Exception:  # noqa: BLE001
                final_report = f"{draft}\n\n---\n\n## 用户补充要求\n{feedback}"
        else:
            final_report = f"{draft}\n\n---\n\n## 用户补充要求\n{feedback}"

    summary = "最终报告已生成。"
    await runtime.emit_thinking(session_id, _NODE, summary)
    await runtime.emit_node_complete(session_id, _NODE, 98, summary)

    return {
        **state,
        "final_report": final_report,
        "current_node": _NODE,
        "progress": 98,
        "messages": append_message(state, summary),
    }
