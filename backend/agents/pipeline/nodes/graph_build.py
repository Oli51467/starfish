from __future__ import annotations

import asyncio

from agents.pipeline.state import PipelineState, append_message
from models.schemas import KnowledgeGraphBuildRequest, RetrievedPaper
from services.graphrag_service import get_graphrag_service
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "graph_build"


def _format_search_range(input_type: str, paper_range_years: int | None) -> str:
    if input_type != "domain":
        return "-"
    if isinstance(paper_range_years, int) and paper_range_years > 0:
        return f"近 {paper_range_years} 年"
    return "所有时间"


async def graph_build_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 56)

    graphrag_service = get_graphrag_service()
    prefetched_papers = [
        RetrievedPaper.model_validate(item)
        for item in (state.get("papers") or [])
    ]
    request = KnowledgeGraphBuildRequest(
        query=str(state.get("input_value") or "").strip(),
        max_papers=min(30, max(3, len(prefetched_papers) or 24)),
        max_entities_per_paper=6,
        prefetched_papers=prefetched_papers,
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
