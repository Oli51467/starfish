from __future__ import annotations

import asyncio
from collections import Counter
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


def _count_lineage_nodes(lineage_payload: dict | None) -> int:
    if not isinstance(lineage_payload, dict):
        return 0
    return len(lineage_payload.get("ancestors") or []) + len(lineage_payload.get("descendants") or [])


def _resolve_lineage_depth(state: PipelineState) -> int:
    paper_count = len(state.get("papers") or [])
    if paper_count >= 24:
        return 4
    if paper_count >= 14:
        return 3
    return 2


def _normalize_paper_item(paper: dict | None) -> dict:
    safe = dict(paper or {})
    paper_id = str(safe.get("paper_id") or "").strip()
    title = str(safe.get("title") or "").strip()
    if not paper_id:
        paper_id = f"paper-{abs(hash(title))}" if title else ""
    return {
        "paper_id": paper_id,
        "title": title or paper_id or "Unknown Paper",
        "authors": list(safe.get("authors") or []),
        "year": _safe_int(safe.get("year"), 0),
        "month": _safe_int(safe.get("month"), 0),
        "publication_date": str(safe.get("publication_date") or "").strip(),
        "citation_count": max(0, _safe_int(safe.get("citation_count"), 0)),
        "venue": str(safe.get("venue") or "").strip(),
        "abstract": str(safe.get("abstract") or "").strip(),
        "arxiv_id": str(safe.get("arxiv_id") or "").strip(),
    }


def _build_publication_date(year: int, month: int, explicit_date: str) -> str | None:
    if explicit_date:
        return explicit_date
    if year <= 0:
        return None
    safe_month = month if 1 <= month <= 12 else 1
    return f"{year:04d}-{safe_month:02d}-01"


def _lineage_node(
    paper: dict,
    *,
    node_type: str,
    ctype: str | None,
    hop: int,
) -> dict:
    year = _safe_int(paper.get("year"), 0)
    month = _safe_int(paper.get("month"), 0)
    paper_id = str(paper.get("paper_id") or "").strip()
    return {
        "id": paper_id or f"paper-{abs(hash(str(paper.get('title') or '')))}",
        "paper_id": paper_id,
        "title": str(paper.get("title") or "").strip() or paper_id or "Unknown Paper",
        "authors": list(paper.get("authors") or []),
        "year": year if year > 0 else None,
        "publication_date": _build_publication_date(year, month, str(paper.get("publication_date") or "").strip()),
        "citation_count": max(0, _safe_int(paper.get("citation_count"), 0)),
        "venue": str(paper.get("venue") or "").strip() or None,
        "abstract": str(paper.get("abstract") or "").strip() or None,
        "arxiv_id": str(paper.get("arxiv_id") or "").strip() or None,
        "node_type": node_type,
        "ctype": ctype,
        "relevance": None,
        "hop": max(0, int(hop)),
        "relation_type": ctype,
        "relation_description": "",
        "generation": max(0, int(hop)),
    }


def _build_local_lineage_fallback(state: PipelineState, *, seed_paper_id: str) -> dict | None:
    normalized_papers = [
        _normalize_paper_item(item)
        for item in (state.get("papers") or [])
        if isinstance(item, dict)
    ]
    normalized_papers = [item for item in normalized_papers if str(item.get("paper_id") or "").strip()]
    if not normalized_papers:
        return None

    root_paper = None
    safe_seed_id = str(seed_paper_id or "").strip()
    if safe_seed_id:
        root_paper = next(
            (item for item in normalized_papers if str(item.get("paper_id") or "").strip() == safe_seed_id),
            None,
        )
    if root_paper is None:
        root_paper = normalized_papers[0]

    root_id = str(root_paper.get("paper_id") or "").strip()
    root_year = _safe_int(root_paper.get("year"), 0)
    candidates = [item for item in normalized_papers if str(item.get("paper_id") or "").strip() != root_id]
    candidates.sort(
        key=lambda item: (_safe_int(item.get("citation_count"), 0), _safe_int(item.get("year"), 0)),
        reverse=True,
    )

    if root_year > 0:
        primary_ancestors = [item for item in candidates if 0 < _safe_int(item.get("year"), 0) <= root_year]
        primary_descendants = [item for item in candidates if _safe_int(item.get("year"), 0) >= root_year]
    else:
        midpoint = max(1, len(candidates) // 2)
        primary_ancestors = candidates[:midpoint]
        primary_descendants = candidates[midpoint:]

    secondary_pool = list(candidates)
    target_total = min(28, max(8, len(candidates)))
    ancestor_limit = min(14, max(3, target_total // 2))
    descendant_limit = min(14, max(3, target_total - ancestor_limit))

    used_ids: set[str] = set()

    def pick_candidates(primary_pool: list[dict], limit: int) -> list[dict]:
        picked: list[dict] = []
        for source in (primary_pool, secondary_pool):
            for paper in source:
                paper_id = str(paper.get("paper_id") or "").strip()
                if not paper_id or paper_id in used_ids or paper_id == root_id:
                    continue
                picked.append(paper)
                used_ids.add(paper_id)
                if len(picked) >= limit:
                    return picked
        return picked

    ancestors_src = pick_candidates(primary_ancestors, ancestor_limit)
    descendants_src = pick_candidates(primary_descendants, descendant_limit)

    ancestors: list[dict] = []
    for paper in ancestors_src:
        paper_year = _safe_int(paper.get("year"), 0)
        hop = max(1, root_year - paper_year) if (root_year > 0 and paper_year > 0) else 1
        ancestors.append(
            _lineage_node(
                paper,
                node_type="ancestor",
                ctype="supporting",
                hop=min(4, hop),
            )
        )

    descendants: list[dict] = []
    for paper in descendants_src:
        paper_year = _safe_int(paper.get("year"), 0)
        hop = max(1, paper_year - root_year) if (root_year > 0 and paper_year > 0) else 1
        descendants.append(
            _lineage_node(
                paper,
                node_type="descendant",
                ctype="extending",
                hop=min(4, hop),
            )
        )

    edges: list[dict] = []
    for item in ancestors:
        item_id = str(item.get("paper_id") or "").strip()
        if item_id and root_id:
            edges.append(
                {
                    "source": item_id,
                    "target": root_id,
                    "ctype": str(item.get("ctype") or "supporting"),
                    "hop": max(1, _safe_int(item.get("hop"), 1)),
                }
            )
    for item in descendants:
        item_id = str(item.get("paper_id") or "").strip()
        if item_id and root_id:
            edges.append(
                {
                    "source": root_id,
                    "target": item_id,
                    "ctype": str(item.get("ctype") or "extending"),
                    "hop": max(1, _safe_int(item.get("hop"), 1)),
                }
            )

    all_years = [
        _safe_int(item.get("year"), 0)
        for item in [root_paper, *ancestors_src, *descendants_src]
        if _safe_int(item.get("year"), 0) > 0
    ]
    year_min = min(all_years) if all_years else 0
    year_max = max(all_years) if all_years else 0

    relation_counter = Counter(
        str(item.get("ctype") or "").strip().lower()
        for item in [*ancestors, *descendants]
        if str(item.get("ctype") or "").strip()
    )
    stats = {
        "total_ancestors": len(ancestors),
        "total_descendants": len(descendants),
        "type_distribution": dict(relation_counter),
        "has_controversy": False,
        "controversy_count": 0,
        "year_range": [year_min, year_max],
    }

    return {
        "root": _lineage_node(root_paper, node_type="root", ctype=None, hop=0),
        "ancestors": ancestors,
        "descendants": descendants,
        "edges": edges,
        "stats": stats,
        "cached": True,
    }


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

    safe_errors = list(state.get("errors") or [])
    warnings: list[str] = []

    async def run_with_soft_timeout(coro, *, timeout_seconds: int, label: str):
        task = asyncio.create_task(coro)
        done, _ = await asyncio.wait({task}, timeout=max(1, int(timeout_seconds)))
        if task in done:
            try:
                return await task
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{label}: {summarize_exception(exc)}")
                return None

        task.cancel()
        warnings.append(f"{label}: timeout")
        return None

    async def lineage_task():
        if not seed_paper_id:
            warnings.append("lineage_task_skipped: missing_seed_paper")
            return None
        depth = _resolve_lineage_depth(state)
        lineage = await run_with_soft_timeout(
            lineage_service.get_lineage(
                paper_id=seed_paper_id,
                ancestor_depth=depth,
                descendant_depth=depth,
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
            warnings.append(f"critic_task_failed: {summarize_exception(exc)}")
            return _fallback_critic_notes(state)

    lineage_data, research_gaps, critic_notes = await asyncio.gather(
        lineage_task(),
        gaps_task(),
        critic_task(),
        return_exceptions=False,
    )

    lineage_node_count = 0
    local_lineage_fallback: dict | None = None
    if not isinstance(lineage_data, dict):
        local_lineage_fallback = _build_local_lineage_fallback(state, seed_paper_id=seed_paper_id)
        if isinstance(local_lineage_fallback, dict):
            lineage_data = local_lineage_fallback
            warnings.append("lineage_fallback_applied: local_graph_heuristic")
    else:
        local_lineage_fallback = _build_local_lineage_fallback(state, seed_paper_id=seed_paper_id)
        current_count = _count_lineage_nodes(lineage_data)
        local_count = _count_lineage_nodes(local_lineage_fallback)
        min_expected = min(20, max(8, len(state.get("papers") or []) // 2))
        if current_count < min_expected and local_count > current_count:
            lineage_data = local_lineage_fallback
            warnings.append(
                f"lineage_result_upgraded: local_graph_heuristic ({current_count}->{local_count})"
            )

    merged_critic_notes = [str(item).strip() for item in (critic_notes or []) if str(item).strip()]
    for warning in warnings:
        safe_warning = str(warning).strip()
        if not safe_warning:
            continue
        normalized = f"执行提示：{safe_warning}"
        if normalized not in merged_critic_notes:
            merged_critic_notes.append(normalized)
    merged_critic_notes = merged_critic_notes[:8]

    if isinstance(lineage_data, dict):
        lineage_node_count = len(lineage_data.get("ancestors") or []) + len(lineage_data.get("descendants") or [])

    summary = (
        f"并行分析完成：血缘节点 {lineage_node_count}，"
        f"研究空白 {len(research_gaps)}。"
    )
    await runtime.emit_thinking(session_id, _NODE, summary)
    await runtime.emit_node_complete(session_id, _NODE, 96, summary)

    return {
        **state,
        "lineage_data": lineage_data,
        "research_gaps": research_gaps,
        "critic_notes": merged_critic_notes,
        "errors": safe_errors,
        "current_node": _NODE,
        "progress": 96,
        "messages": append_message(state, summary),
    }
