from __future__ import annotations

import asyncio
import re
from typing import Any

from agents.pipeline.state import PipelineState, append_message
from models.schemas import KnowledgeGraphRetrieveRequest
from services.graphrag_service import get_graphrag_service
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "search"
_MIN_SEARCH_PAPERS = 6


def _resolve_seed_paper(input_type: str, papers: list[dict]) -> dict | None:
    if input_type not in {"arxiv_id", "doi"}:
        return None
    if not papers:
        return None
    top = papers[0]
    if not str(top.get("paper_id") or "").strip():
        return None
    return top


def _normalize_year_range(raw_value: Any) -> int | None:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return min(30, parsed)


def _iter_relaxed_ranges(year_range: int | None) -> list[int | None]:
    if year_range is None:
        return [None]
    if year_range <= 1:
        return [year_range, 2, 3, None]
    if year_range == 2:
        return [year_range, 3, None]
    return [year_range, None]


def _paper_identity(paper: dict[str, Any]) -> str:
    paper_id = str(paper.get("paper_id") or "").strip().lower()
    if paper_id:
        return f"id:{paper_id}"
    title = re.sub(r"\s+", " ", str(paper.get("title") or "").strip().lower())
    if title:
        return f"title:{title}"
    return ""


def _merge_unique_papers(primary: list[dict], secondary: list[dict], *, limit: int = 30) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for source in (primary, secondary):
        for item in source:
            if not isinstance(item, dict):
                continue
            key = _paper_identity(item)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(item)
            if len(merged) >= max(1, int(limit)):
                return merged
    return merged


def _build_retrieve_request(state: PipelineState, paper_range_years: int | None) -> KnowledgeGraphRetrieveRequest:
    return KnowledgeGraphRetrieveRequest(
        query=str(state.get("input_value") or "").strip(),
        max_papers=30,
        input_type=str(state.get("input_type") or "domain").strip(),
        quick_mode=bool(state.get("quick_mode")),
        paper_range_years=paper_range_years,
    )


def _format_range_text(year_range: int | None) -> str:
    if year_range is None:
        return "所有时间"
    return f"近 {year_range} 年"


async def search_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 18)

    graphrag_service = get_graphrag_service()
    requested_range = _normalize_year_range(state.get("paper_range_years"))
    request = _build_retrieve_request(state, requested_range)
    retrieval = await asyncio.to_thread(graphrag_service.retrieve_papers, request)

    papers = [paper.model_dump(mode="json") for paper in retrieval.papers]
    relaxed_search_applied = False
    relaxed_from: int | None = None
    relaxed_to: int | None = None
    if str(request.input_type or "").strip().lower() == "domain" and len(papers) < _MIN_SEARCH_PAPERS:
        for candidate_range in _iter_relaxed_ranges(requested_range):
            if candidate_range == requested_range:
                continue
            fallback_request = _build_retrieve_request(state, candidate_range)
            fallback_retrieval = await asyncio.to_thread(graphrag_service.retrieve_papers, fallback_request)
            fallback_papers = [paper.model_dump(mode="json") for paper in fallback_retrieval.papers]
            merged = _merge_unique_papers(papers, fallback_papers, limit=30)
            if len(merged) > len(papers):
                papers = merged
                retrieval = fallback_retrieval
                relaxed_search_applied = True
                relaxed_from = requested_range
                relaxed_to = candidate_range
            if len(papers) >= _MIN_SEARCH_PAPERS:
                break

    seed_paper = _resolve_seed_paper(request.input_type, papers)
    resolved_query = str(retrieval.query or request.query).strip() or str(request.query or "").strip()
    next_input_value = str(state.get("input_value") or "").strip()
    if str(request.input_type or "").strip().lower() == "domain" and resolved_query:
        next_input_value = resolved_query

    if str(request.input_type or "").strip().lower() == "domain" and resolved_query and resolved_query != str(request.query or "").strip():
        summary = f"检索完成，已将检索词标准化为“{resolved_query}”，共筛选 {len(papers)} 篇论文。"
    else:
        summary = f"检索完成，共筛选 {len(papers)} 篇论文。"
    if relaxed_search_applied:
        summary = (
            f"{summary} 当前时间范围结果较少，已从{_format_range_text(relaxed_from)}"
            f"自动放宽到{_format_range_text(relaxed_to)}补充候选。"
        )
    await runtime.emit_thinking(session_id, _NODE, summary)
    await runtime.emit_node_complete(session_id, _NODE, 25, summary)

    return {
        **state,
        "input_value": next_input_value,
        "papers": papers,
        "seed_paper": seed_paper,
        "search_fallback_applied": relaxed_search_applied,
        "search_fallback_from_years": relaxed_from,
        "search_fallback_to_years": relaxed_to,
        "current_node": _NODE,
        "progress": 25,
        "messages": append_message(state, summary),
    }
