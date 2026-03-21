from __future__ import annotations

import asyncio
from statistics import mean

from agents.pipeline.nodes.utils import parse_json_array, summarize_exception
from agents.pipeline.state import PipelineState, append_message
from core.llm_client import chat, is_configured
from services.lineage_service import get_lineage_service
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "parallel"


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _get_seed_paper_id(state: PipelineState) -> str:
    seed = state.get("seed_paper") or {}
    safe_seed = str(seed.get("paper_id") or "").strip()
    if safe_seed:
        return safe_seed
    for paper in state.get("papers") or []:
        paper_id = str(paper.get("paper_id") or "").strip()
        if paper_id:
            return paper_id
    return ""


def _top_papers(state: PipelineState, limit: int = 5) -> list[dict]:
    papers = list(state.get("papers") or [])
    papers.sort(key=lambda item: _safe_int(item.get("citation_count"), 0), reverse=True)
    return papers[: max(1, limit)]


def _fallback_critic_notes(state: PipelineState) -> list[str]:
    papers = state.get("papers") or []
    years = [_safe_int(item.get("year"), 0) for item in papers if _safe_int(item.get("year"), 0) > 0]
    notes: list[str] = []
    if years and max(years) - min(years) < 4:
        notes.append("时间跨度偏窄，建议补充更早相关工作。")
    if len(papers) < 10:
        notes.append("论文样本偏少，建议扩展检索规模。")
    notes.append("建议补充不同技术路线的对照研究。")
    return notes[:4]


def _build_research_gaps(state: PipelineState) -> list[dict]:
    papers = list(state.get("papers") or [])
    if not papers:
        return []

    years = [_safe_int(item.get("year"), 0) for item in papers if _safe_int(item.get("year"), 0) > 0]
    citation_values = [_safe_int(item.get("citation_count"), 0) for item in papers]
    avg_citation = int(mean(citation_values)) if citation_values else 0

    gaps: list[dict] = []
    if years:
        span = max(years) - min(years)
        if span < 5:
            gaps.append(
                {
                    "gap_id": "gap-time-span",
                    "title": "长期脉络覆盖不足",
                    "description": "当前样本时间跨度较短，缺少历史基线对照。",
                    "opportunity_score": 74,
                }
            )

    low_citation_ratio = 0.0
    if citation_values:
        low_citation_ratio = sum(1 for value in citation_values if value <= max(3, avg_citation // 5)) / len(citation_values)
    if low_citation_ratio > 0.5:
        gaps.append(
            {
                "gap_id": "gap-evidence-strength",
                "title": "证据强度分布不均",
                "description": "低引用样本占比较高，建议加入高影响力对照文献。",
                "opportunity_score": 69,
            }
        )

    gaps.append(
        {
            "gap_id": "gap-cross-method",
            "title": "跨方法对比不足",
            "description": "建议构建统一评测框架比较不同技术路线。",
            "opportunity_score": 72,
        }
    )
    return gaps[:3]


async def _critic_with_llm(state: PipelineState) -> list[str]:
    papers = _top_papers(state, limit=12)
    paper_lines = [
        f"- {str(item.get('title') or '')[:120]}（{_safe_int(item.get('year'), 0)}）引用{_safe_int(item.get('citation_count'), 0)}"
        for item in papers
        if str(item.get("title") or "").strip()
    ]
    user_prompt = (
        f"研究目标：{state.get('research_goal') or state.get('input_value') or ''}\n"
        f"论文列表：\n{chr(10).join(paper_lines)}\n"
        "请返回 3-5 条简洁批评意见 JSON 数组。"
    )
    response = await asyncio.wait_for(
        asyncio.to_thread(
            chat,
            [
                {
                    "role": "system",
                    "content": "你是科研审查者，请输出 JSON 数组，每条一句，不超过30字。",
                },
                {"role": "user", "content": user_prompt},
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

    parsed = parse_json_array(content)
    notes = [str(item).strip() for item in parsed if str(item).strip()]
    return notes[:5]


async def parallel_analysis_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 92)

    seed_paper_id = _get_seed_paper_id(state)

    lineage_service = get_lineage_service()

    errors = list(state.get("errors") or [])

    async def run_with_soft_timeout(coro, *, timeout_seconds: int, label: str):
        task = asyncio.create_task(coro)
        done, _ = await asyncio.wait({task}, timeout=max(1, int(timeout_seconds)))
        if task in done:
            try:
                return await task
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {summarize_exception(exc)}")
                return None

        task.cancel()
        errors.append(f"{label}: timeout")
        return None

    async def lineage_task():
        if not seed_paper_id:
            return None
        lineage = await run_with_soft_timeout(
            lineage_service.get_lineage(
                paper_id=seed_paper_id,
                ancestor_depth=2,
                descendant_depth=2,
                citation_types=None,
                force_refresh=False,
            ),
            timeout_seconds=35,
            label="lineage_task_failed",
        )
        if lineage is None:
            return None
        return lineage.model_dump(mode="json")

    async def gaps_task():
        return _build_research_gaps(state)

    async def critic_task():
        if not is_configured():
            return _fallback_critic_notes(state)
        try:
            notes = await _critic_with_llm(state)
            return notes or _fallback_critic_notes(state)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"critic_task_failed: {summarize_exception(exc)}")
            return _fallback_critic_notes(state)

    lineage_data, research_gaps, critic_notes = await asyncio.gather(
        lineage_task(),
        gaps_task(),
        critic_task(),
        return_exceptions=False,
    )

    lineage_node_count = 0
    if isinstance(lineage_data, dict):
        lineage_node_count = len(lineage_data.get("ancestors") or []) + len(lineage_data.get("descendants") or [])

    summary = (
        f"并行分析完成：血缘节点 {lineage_node_count}，"
        f"研究空白 {len(research_gaps)}。"
    )
    await runtime.emit_thinking(session_id, _NODE, summary)
    await runtime.emit_node_complete(session_id, _NODE, 100, summary)

    return {
        **state,
        "lineage_data": lineage_data,
        "research_gaps": research_gaps,
        "critic_notes": critic_notes,
        "errors": errors,
        "current_node": _NODE,
        "progress": 100,
        "messages": append_message(state, summary),
    }
