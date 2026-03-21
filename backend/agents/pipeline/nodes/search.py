from __future__ import annotations

import asyncio

from agents.pipeline.state import PipelineState, append_message
from models.schemas import KnowledgeGraphRetrieveRequest
from services.graphrag_service import get_graphrag_service
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "search"


def _resolve_seed_paper(input_type: str, papers: list[dict]) -> dict | None:
    if input_type not in {"arxiv_id", "doi"}:
        return None
    if not papers:
        return None
    top = papers[0]
    if not str(top.get("paper_id") or "").strip():
        return None
    return top


async def search_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 18)

    graphrag_service = get_graphrag_service()
    request = KnowledgeGraphRetrieveRequest(
        query=str(state.get("input_value") or "").strip(),
        max_papers=30,
        input_type=str(state.get("input_type") or "domain").strip(),
        quick_mode=bool(state.get("quick_mode")),
        paper_range_years=state.get("paper_range_years"),
    )
    retrieval = await asyncio.to_thread(graphrag_service.retrieve_papers, request)

    papers = [paper.model_dump(mode="json") for paper in retrieval.papers]
    seed_paper = _resolve_seed_paper(request.input_type, papers)
    resolved_query = str(retrieval.query or request.query).strip() or str(request.query or "").strip()
    next_input_value = str(state.get("input_value") or "").strip()
    if str(request.input_type or "").strip().lower() == "domain" and resolved_query:
        next_input_value = resolved_query

    if str(request.input_type or "").strip().lower() == "domain" and resolved_query and resolved_query != str(request.query or "").strip():
        summary = f"检索完成，已将检索词标准化为“{resolved_query}”，共筛选 {len(papers)} 篇论文。"
    else:
        summary = f"检索完成，共筛选 {len(papers)} 篇论文。"
    await runtime.emit_thinking(session_id, _NODE, summary)
    await runtime.emit_node_complete(session_id, _NODE, 25, summary)

    return {
        **state,
        "input_value": next_input_value,
        "papers": papers,
        "seed_paper": seed_paper,
        "current_node": _NODE,
        "progress": 25,
        "messages": append_message(state, summary),
    }
