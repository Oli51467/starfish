from __future__ import annotations

import asyncio
from typing import Any

from agents.pipeline.state import PipelineState, append_message
from models.schemas import KnowledgeGraphBuildRequest, KnowledgeGraphRetrieveRequest, RetrievedPaper
from services.graphrag_service import get_graphrag_service
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "graph_build"
_MIN_PREFETCHED_PAPERS = 48
_TARGET_PREFETCHED_PAPERS = 72
_MAX_BUILD_PAPERS = 180


def _runtime_event_enabled(state: PipelineState) -> bool:
    return not bool(state.get("runtime_silent_mode"))


def _format_search_range(input_type: str, paper_range_years: int | None) -> str:
    if input_type != "domain":
        return "-"
    if isinstance(paper_range_years, int) and paper_range_years > 0:
        return f"近 {paper_range_years} 年"
    return "所有时间"


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


def _resolve_node_kind(node: dict[str, Any]) -> str:
    return str(node.get("kind") or node.get("type") or "").strip().lower()


def _resolve_node_tier(node: dict[str, Any]) -> int:
    meta = node.get("meta") if isinstance(node.get("meta"), dict) else {}
    return max(1, min(3, _safe_int(meta.get("tier", node.get("tier", 3)), 3)))


def _normalize_retrieve_input_type(raw_value: Any) -> str:
    normalized = str(raw_value or "").strip().lower()
    if normalized in {"arxiv_id", "doi"}:
        return normalized
    return "domain"


def _paper_identity(paper: RetrievedPaper) -> str:
    paper_id = str(getattr(paper, "paper_id", "") or "").strip().lower()
    if paper_id:
        return f"id:{paper_id}"
    title = str(getattr(paper, "title", "") or "").strip().lower()
    if title:
        return f"title:{title}"
    return ""


def _merge_prefetched_papers(
    primary: list[RetrievedPaper],
    secondary: list[RetrievedPaper],
    *,
    limit: int = _MAX_BUILD_PAPERS,
) -> list[RetrievedPaper]:
    merged: list[RetrievedPaper] = []
    seen: set[str] = set()
    for source in (primary, secondary):
        for item in source:
            if not isinstance(item, RetrievedPaper):
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


def _build_graph_stream_stage_payload(
    graph_payload: dict[str, Any],
    *,
    max_paper_tier: int,
) -> dict[str, Any]:
    nodes = list(graph_payload.get("nodes") or [])
    edges = list(graph_payload.get("edges") or [])
    if not nodes:
        return {
            **dict(graph_payload),
            "nodes": [],
            "edges": [],
        }

    included_paper_ids: set[str] = set()
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        if _resolve_node_kind(node) != "paper":
            continue
        if _resolve_node_tier(node) <= max_paper_tier:
            included_paper_ids.add(node_id)

    if not included_paper_ids:
        return {
            **dict(graph_payload),
            "nodes": [],
            "edges": [],
        }

    allowed_node_ids = set(included_paper_ids)
    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        if source in included_paper_ids or target in included_paper_ids:
            allowed_node_ids.add(source)
            allowed_node_ids.add(target)

    stage_nodes = [node for node in nodes if str(node.get("id") or "").strip() in allowed_node_ids]
    stage_edges = [
        edge
        for edge in edges
        if str(edge.get("source") or "").strip() in allowed_node_ids
        and str(edge.get("target") or "").strip() in allowed_node_ids
    ]
    return {
        **dict(graph_payload),
        "nodes": stage_nodes,
        "edges": stage_edges,
    }


async def graph_build_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]
    emit_events = _runtime_event_enabled(state)

    await runtime.ensure_active(session_id)
    if emit_events:
        await runtime.emit_node_start(session_id, _NODE, 56)

    graphrag_service = get_graphrag_service()
    prefetched_papers = [
        RetrievedPaper.model_validate(item)
        for item in (state.get("papers") or [])
    ]
    if len(prefetched_papers) < _MIN_PREFETCHED_PAPERS:
        base_query = str(state.get("input_value") or "").strip()
        if base_query:
            try:
                retrieve_request = KnowledgeGraphRetrieveRequest(
                    query=base_query,
                    max_papers=min(_MAX_BUILD_PAPERS, _TARGET_PREFETCHED_PAPERS + 36),
                    input_type=_normalize_retrieve_input_type(state.get("input_type")),
                    quick_mode=bool(state.get("quick_mode")),
                    paper_range_years=state.get("paper_range_years"),
                )
                supplemental = await asyncio.to_thread(graphrag_service.retrieve_papers, retrieve_request)
                prefetched_papers = _merge_prefetched_papers(
                    prefetched_papers,
                    list(supplemental.papers or []),
                    limit=_MAX_BUILD_PAPERS,
                )
                if retrieve_request.input_type == "domain":
                    expanded_domains = graphrag_service.expand_graph_domains(
                        query=base_query,
                        target_domains=5,
                    )
                    domain_requests = []
                    for domain_query in expanded_domains:
                        normalized_domain_query = str(domain_query or "").strip()
                        if not normalized_domain_query:
                            continue
                        domain_requests.append(
                            retrieve_request.model_copy(
                                update={
                                    "query": normalized_domain_query,
                                    "max_papers": min(_MAX_BUILD_PAPERS, 30),
                                }
                            )
                        )
                    if domain_requests:
                        domain_results = await asyncio.gather(
                            *[
                                asyncio.to_thread(graphrag_service.retrieve_papers, domain_request)
                                for domain_request in domain_requests
                            ],
                            return_exceptions=True,
                        )
                        for domain_result in domain_results:
                            if isinstance(domain_result, Exception):
                                continue
                            prefetched_papers = _merge_prefetched_papers(
                                prefetched_papers,
                                list(domain_result.papers or []),
                                limit=_MAX_BUILD_PAPERS,
                            )
            except Exception:  # noqa: BLE001
                # Retrieval补充失败时继续使用已有候选，避免阻断建图主流程。
                pass

    request = KnowledgeGraphBuildRequest(
        query=str(state.get("input_value") or "").strip(),
        max_papers=min(_MAX_BUILD_PAPERS, max(_TARGET_PREFETCHED_PAPERS, len(prefetched_papers) or 36)),
        max_entities_per_paper=6,
        prefetched_papers=prefetched_papers,
        paper_range_years=state.get("paper_range_years"),
        research_type=str(state.get("input_type") or "unknown"),
        search_input=str(state.get("input_value") or "").strip(),
        search_range=_format_search_range(
            str(state.get("input_type") or "domain"),
            state.get("paper_range_years"),
        ),
    )

    result = await asyncio.to_thread(graphrag_service.build_knowledge_graph, request)
    graph_payload = result.model_dump(mode="json")
    nodes = list(graph_payload.get("nodes") or [])
    edges = list(graph_payload.get("edges") or [])

    summary = f"图谱构建完成，节点 {len(nodes)} 个，关系 {len(edges)} 条。"
    if emit_events:
        tier2_graph = _build_graph_stream_stage_payload(graph_payload, max_paper_tier=2)
        await runtime.emit_graph_stream(
            session_id,
            stage="tier2",
            query=str(request.query or "").strip(),
            summary=str(graph_payload.get("summary") or ""),
            graph=tier2_graph,
            stats={
                "node_count": len(list(tier2_graph.get("nodes") or [])),
                "edge_count": len(list(tier2_graph.get("edges") or [])),
            },
        )
        await runtime.emit_graph_stream(
            session_id,
            stage="tier3",
            query=str(request.query or "").strip(),
            summary=str(graph_payload.get("summary") or ""),
            graph=graph_payload,
            stats={
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
        )
        await runtime.emit_thinking(session_id, _NODE, summary)
        await runtime.emit_node_complete(session_id, _NODE, 72, summary)

    return {
        **state,
        "graph_id": result.graph_id,
        "graph_nodes": nodes,
        "graph_edges": edges,
        "graph_payload": graph_payload,
        "current_node": _NODE,
        "progress": 72,
        "messages": append_message(state, summary),
    }
