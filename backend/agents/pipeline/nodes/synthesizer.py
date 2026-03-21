from __future__ import annotations

import asyncio

from agents.pipeline.state import PipelineState, append_message
from core.llm_client import chat, is_configured
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "synthesizer"


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _build_fallback_report(state: PipelineState) -> str:
    papers = list(state.get("papers") or [])
    top_papers = sorted(
        papers,
        key=lambda item: _safe_int(item.get("citation_count"), 0),
        reverse=True,
    )[:5]

    lineage = state.get("lineage_data") if isinstance(state.get("lineage_data"), dict) else {}
    lineage_count = len(lineage.get("ancestors") or []) + len(lineage.get("descendants") or [])

    gaps = state.get("research_gaps") or []
    critic_notes = state.get("critic_notes") or []

    reference_lines = []
    for index, paper in enumerate(top_papers, start=1):
        title = str(paper.get("title") or "Untitled").strip()
        year = _safe_int(paper.get("year"), 0)
        reference_lines.append(f"{index}. {title} ({year or '-'})")

    gap_lines = [
        f"- {str(item.get('title') or '').strip()}：{str(item.get('description') or '').strip()}"
        for item in gaps[:3]
        if str(item.get("title") or "").strip()
    ]

    critic_lines = [f"- {str(item).strip()}" for item in critic_notes[:5] if str(item).strip()]
    if not critic_lines:
        critic_lines = ["- 当前结果可用，但建议补充更广泛来源。"]

    report = f"""
# AutoResearch Report

## 1. 研究目标与范围
- 目标：{state.get('research_goal') or state.get('input_value') or '-'}
- 输入类型：{state.get('input_type')}
- 论文规模：{len(papers)}

## 2. 领域全景
- 图谱节点：{len(state.get('graph_nodes') or [])}
- 图谱关系：{len(state.get('graph_edges') or [])}

## 3. 核心论文分析（Top 5）
{chr(10).join(reference_lines) if reference_lines else '- 暂无可用论文'}

## 4. 技术演化脉络
- 血缘节点总数：{lineage_count}

## 5. 研究空白与机会
{chr(10).join(gap_lines) if gap_lines else '- 暂无明显空白'}

## 6. 批评性审查
{chr(10).join(critic_lines)}

## 7. 研究建议
- 建议 1：补充跨时间跨度的关键文献对照。
- 建议 2：围绕高影响论文构建可复现实验路线。
- 建议 3：针对识别出的空白方向设计最小可验证实验。

## 8. 参考文献
{chr(10).join(reference_lines) if reference_lines else '- 暂无'}
""".strip()
    return report


async def _synthesize_with_llm(state: PipelineState) -> str:
    context = {
        "research_goal": state.get("research_goal"),
        "paper_count": len(state.get("papers") or []),
        "graph_nodes": len(state.get("graph_nodes") or []),
        "graph_edges": len(state.get("graph_edges") or []),
        "lineage": state.get("lineage_data") or {},
        "research_gaps": (state.get("research_gaps") or [])[:3],
        "critic_notes": state.get("critic_notes") or [],
        "top_papers": sorted(
            state.get("papers") or [],
            key=lambda item: _safe_int(item.get("citation_count"), 0),
            reverse=True,
        )[:5],
    }
    response = await asyncio.wait_for(
        asyncio.to_thread(
            chat,
            [
                {
                    "role": "system",
                    "content": (
                        "你是科研综合分析师。"
                        "请输出 Markdown 报告，包含 8 个章节："
                        "研究目标与范围、领域全景、核心论文分析、技术演化脉络、"
                        "研究空白与机会、批评性审查、研究建议、参考文献。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"请基于以下结构化数据生成报告：\n{context}",
                },
            ],
            temperature=0.2,
            timeout=25,
        ),
        timeout=27,
    )

    content = ""
    try:
        content = str(response.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001
        content = ""

    return content or _build_fallback_report(state)


async def synthesizer_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 82)

    if is_configured():
        try:
            report = await _synthesize_with_llm(state)
        except Exception:  # noqa: BLE001
            report = _build_fallback_report(state)
    else:
        report = _build_fallback_report(state)

    preview = report.replace("\n", " ")[:120]
    await runtime.emit_thinking(session_id, _NODE, f"报告草稿预览：{preview}")

    summary = "报告草稿生成完成，等待用户确认。"
    await runtime.emit_node_complete(session_id, _NODE, 88, summary)

    return {
        **state,
        "report_draft": report,
        "current_node": _NODE,
        "progress": 88,
        "messages": append_message(state, summary),
    }
