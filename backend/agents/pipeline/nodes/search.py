from __future__ import annotations

import asyncio
import re
from typing import Any

from agents.pipeline.state import PipelineState, append_message
from models.schemas import KnowledgeGraphRetrieveRequest
from services.graphrag_service import get_graphrag_service
from services.node_scorer import build_aha_summary, score_paper_nodes
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "search"
_MIN_SEARCH_PAPERS = 6
_TIER1_PREVIEW_PAPER_LIMIT = 8
_MAX_SEARCH_PAPERS = 180


def _runtime_event_enabled(state: PipelineState) -> bool:
    return not bool(state.get("runtime_silent_mode"))


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


def _merge_unique_papers(primary: list[dict], secondary: list[dict], *, limit: int = _MAX_SEARCH_PAPERS) -> list[dict]:
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
        max_papers=_MAX_SEARCH_PAPERS,
        input_type=str(state.get("input_type") or "domain").strip(),
        quick_mode=bool(state.get("quick_mode")),
        paper_range_years=paper_range_years,
    )


def _format_range_text(year_range: int | None) -> str:
    if year_range is None:
        return "所有时间"
    return f"近 {year_range} 年"


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, parsed)


def _resolve_preview_year(value: Any) -> int:
    year = _safe_int(value, 0)
    if year <= 0:
        return 0
    return year


def _build_tier1_preview_payload(query: str, papers: list[dict[str, Any]]) -> dict[str, Any]:
    safe_query = str(query or "").strip()
    source_papers = [item for item in papers if isinstance(item, dict)]
    if not source_papers:
        return {
            "summary": build_aha_summary(safe_query, []),
            "papers": [],
            "tier_counts": {"tier1": 0, "tier2": 0, "tier3": 0},
        }

    total = max(1, len(source_papers))
    scored_payload: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(source_papers):
        paper_id = str(item.get("paper_id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not paper_id or not title:
            continue
        query_relevance = max(0.18, min(1.0, 1.0 - (index / total) * 0.82))
        citation_count = _safe_int(item.get("citation_count"))
        year = _resolve_preview_year(item.get("year"))
        scored_payload.append(
            {
                "id": paper_id,
                "title": title,
                "citation_count": citation_count,
                "year": year,
                "internal_citations": 0,
                "query_relevance": query_relevance,
                "semantic_score": query_relevance,
            }
        )
        normalized.append(
            {
                "paper_id": paper_id,
                "title": title,
                "abstract": str(item.get("abstract") or ""),
                "year": year if year > 0 else None,
                "month": _safe_int(item.get("month")),
                "citation_count": citation_count,
                "venue": str(item.get("venue") or "Unknown Venue"),
                "authors": list(item.get("authors") or []),
                "query_relevance": query_relevance,
            }
        )

    scored = score_paper_nodes(scored_payload, max_tier1=3)
    scored_by_id = {str(item.get("id") or ""): item for item in scored}
    ranked = sorted(
        normalized,
        key=lambda item: (
            int((scored_by_id.get(str(item.get("paper_id") or "")) or {}).get("tier", 3)),
            -float((scored_by_id.get(str(item.get("paper_id") or "")) or {}).get("importance_score", 0.0)),
            -int(item.get("citation_count") or 0),
        ),
    )

    preview_papers: list[dict[str, Any]] = []
    for item in ranked[:_TIER1_PREVIEW_PAPER_LIMIT]:
        paper_id = str(item.get("paper_id") or "")
        scored_item = scored_by_id.get(paper_id) or {}
        preview_papers.append(
            {
                **item,
                "importance_score": float(scored_item.get("importance_score", 0.0)),
                "tier": int(scored_item.get("tier", 3) or 3),
                "node_size": float(scored_item.get("node_size", 20.0)),
            }
        )

    return {
        "summary": build_aha_summary(safe_query, scored),
        "papers": preview_papers,
        "tier_counts": {
            "tier1": sum(1 for item in scored if int(item.get("tier", 3)) == 1),
            "tier2": sum(1 for item in scored if int(item.get("tier", 3)) == 2),
            "tier3": sum(1 for item in scored if int(item.get("tier", 3)) == 3),
        },
    }


async def search_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]
    emit_events = _runtime_event_enabled(state)

    await runtime.ensure_active(session_id)
    if emit_events:
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
            merged = _merge_unique_papers(papers, fallback_papers, limit=_MAX_SEARCH_PAPERS)
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
    if emit_events:
        tier1_preview = _build_tier1_preview_payload(resolved_query or request.query, papers)
        await runtime.emit_graph_stream(
            session_id,
            stage="tier1",
            query=resolved_query or request.query,
            summary=str(tier1_preview.get("summary") or summary),
            papers=list(tier1_preview.get("papers") or []),
            stats={
                "selected_paper_count": len(papers),
                **dict(tier1_preview.get("tier_counts") or {}),
            },
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
