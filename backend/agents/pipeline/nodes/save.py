from __future__ import annotations

import asyncio

from agents.pipeline.state import PipelineState, append_message
from models.schemas import (
    KnowledgeGraphBuildRequest,
    KnowledgeGraphResponse,
    SavedPaperCreateRequest,
    SavedPaperMetadata,
    UserProfile,
)
from services.collection_service import get_collection_service
from services.pipeline_runtime_service import get_pipeline_runtime_service
from services.research_history_service import get_research_history_service

_NODE = "save"


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _build_pipeline_payload(state: PipelineState) -> dict:
    insight = state.get("insight") if isinstance(state.get("insight"), dict) else {}
    artifact = insight.get("artifact") if isinstance(insight.get("artifact"), dict) else {}
    return {
        "research_goal": state.get("research_goal") or "",
        "execution_plan": list(state.get("execution_plan") or []),
        "final_report": state.get("final_report") or "",
        "checkpoint_feedback": dict(state.get("checkpoint_feedback") or {}),
        "insight": {
            "status": str(insight.get("status") or ""),
            "summary": str(insight.get("summary") or ""),
            "language": str(insight.get("language") or ""),
            "agent_count": _safe_int(insight.get("agent_count"), 0),
            "exploration_depth": _safe_int(insight.get("exploration_depth"), 0),
            "markdown": str(insight.get("markdown") or ""),
            "artifact": {
                "markdown_path": str(artifact.get("markdown_path") or ""),
                "pdf_path": str(artifact.get("pdf_path") or ""),
            } if artifact else {},
            "generated_at": str(insight.get("generated_at") or ""),
        } if insight else {},
        "parallel_outputs_summary": {
            "research_gaps": len(state.get("research_gaps") or []),
            "critic_notes": len(state.get("critic_notes") or []),
        },
    }


def _format_search_range(input_type: str, paper_range_years: int | None) -> str:
    if input_type != "domain":
        return "-"
    if isinstance(paper_range_years, int) and paper_range_years > 0:
        return f"近 {paper_range_years} 年"
    return "所有时间"


def _top_papers(state: PipelineState, limit: int = 5) -> list[dict]:
    papers = list(state.get("papers") or [])
    papers.sort(key=lambda item: _safe_int(item.get("citation_count"), 0), reverse=True)
    return papers[: max(1, limit)]


def _paper_metadata_from_dict(payload: dict) -> SavedPaperMetadata:
    return SavedPaperMetadata(
        title=str(payload.get("title") or "").strip(),
        abstract=str(payload.get("abstract") or "").strip(),
        authors=[str(item).strip() for item in (payload.get("authors") or []) if str(item).strip()],
        year=_safe_int(payload.get("year"), 0) or None,
        publication_date=str(payload.get("publication_date") or "").strip(),
        citation_count=max(0, _safe_int(payload.get("citation_count"), 0)),
        fields_of_study=[str(item).strip() for item in (payload.get("fields_of_study") or []) if str(item).strip()],
        venue=str(payload.get("venue") or "").strip(),
        url=str(payload.get("url") or "").strip() or None,
    )


async def _save_top_papers(user: UserProfile, state: PipelineState, errors: list[str]) -> None:
    collection_service = get_collection_service()
    top_papers = _top_papers(state, limit=5)

    for paper in top_papers:
        paper_id = str(paper.get("paper_id") or "").strip()
        if not paper_id:
            continue
        request = SavedPaperCreateRequest(
            paper_id=paper_id,
            collection_ids=[],
            metadata=_paper_metadata_from_dict(paper),
            save_source="auto_research",
        )
        try:
            await asyncio.to_thread(
                collection_service.save_paper,
                user=user,
                request=request,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"save_paper_failed:{paper_id}:{str(exc)}")


async def save_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 99)

    errors = list(state.get("errors") or [])

    user = UserProfile(
        id=str(state.get("user_id") or "").strip(),
        email=str(state.get("user_email") or "").strip(),
        name=str(state.get("user_name") or "").strip(),
        picture=None,
    )

    history_service = get_research_history_service()

    history_id = None
    graph_payload = state.get("graph_payload") or {}
    try:
        graph_response = KnowledgeGraphResponse.model_validate(graph_payload)
        request = KnowledgeGraphBuildRequest(
            query=str(graph_response.query or state.get("input_value") or "").strip(),
            max_papers=min(30, max(3, len(state.get("papers") or []))),
            max_entities_per_paper=6,
            prefetched_papers=[],
            research_type=str(state.get("input_type") or "unknown"),
            search_input=str(state.get("input_value") or "").strip(),
            search_range=_format_search_range(
                str(state.get("input_type") or "domain"),
                state.get("paper_range_years"),
            ),
        )
        history_id = await asyncio.to_thread(
            history_service.record_graph_result,
            user=user,
            request=request,
            graph=graph_response,
        )
        if history_id:
            await asyncio.to_thread(
                history_service.update_pipeline_payload,
                user=user,
                history_id=history_id,
                pipeline_payload=_build_pipeline_payload(state),
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"history_save_failed:{str(exc)}")

    await _save_top_papers(user, state, errors)

    summary = "报告与核心论文已保存。"
    await runtime.emit_thinking(session_id, _NODE, summary)
    await runtime.emit_node_complete(session_id, _NODE, 100, summary)

    return {
        **state,
        "history_id": history_id,
        "report_id": history_id,
        "errors": errors,
        "current_node": _NODE,
        "progress": 100,
        "messages": append_message(state, summary),
    }
