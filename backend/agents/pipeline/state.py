from __future__ import annotations

from typing import Any, Literal, TypedDict


PipelineInputType = Literal["arxiv_id", "doi", "domain"]


class PipelineState(TypedDict):
    # input
    input_type: PipelineInputType
    input_value: str
    paper_range_years: int | None
    quick_mode: bool
    user_id: str
    user_email: str
    user_name: str
    session_id: str

    # planner
    research_goal: str
    execution_plan: list[str]
    search_keywords: list[str]

    # search
    papers: list[dict[str, Any]]
    seed_paper: dict[str, Any] | None
    search_fallback_applied: bool
    search_fallback_from_years: int | None
    search_fallback_to_years: int | None

    # graph
    graph_id: str | None
    graph_nodes: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]
    graph_payload: dict[str, Any] | None

    # synthesis context
    research_gaps: list[dict[str, Any]]
    critic_notes: list[str]

    # report
    report_draft: str | None
    final_report: str | None
    report_id: str | None
    history_id: str | None

    # runtime control
    current_node: str
    progress: int
    messages: list[str]
    human_feedback: str | None
    checkpoint_feedback: dict[str, str]
    should_pause: bool
    errors: list[str]


def normalize_pipeline_input_type(raw_value: str) -> PipelineInputType:
    safe = str(raw_value or "").strip().lower()
    if safe == "doi":
        return "doi"
    if safe == "domain":
        return "domain"
    return "arxiv_id"


def build_initial_state(
    *,
    session_id: str,
    user_id: str,
    user_email: str,
    user_name: str,
    input_type: str,
    input_value: str,
    quick_mode: bool,
    paper_range_years: int | None,
) -> PipelineState:
    return PipelineState(
        input_type=normalize_pipeline_input_type(input_type),
        input_value=str(input_value or "").strip(),
        paper_range_years=paper_range_years,
        quick_mode=bool(quick_mode),
        user_id=str(user_id or "").strip(),
        user_email=str(user_email or "").strip(),
        user_name=str(user_name or "").strip(),
        session_id=str(session_id or "").strip(),
        research_goal="",
        execution_plan=[],
        search_keywords=[],
        papers=[],
        seed_paper=None,
        search_fallback_applied=False,
        search_fallback_from_years=None,
        search_fallback_to_years=None,
        graph_id=None,
        graph_nodes=[],
        graph_edges=[],
        graph_payload=None,
        research_gaps=[],
        critic_notes=[],
        report_draft=None,
        final_report=None,
        report_id=None,
        history_id=None,
        current_node="init",
        progress=0,
        messages=[],
        human_feedback=None,
        checkpoint_feedback={},
        should_pause=False,
        errors=[],
    )


def append_message(state: PipelineState, message: str) -> list[str]:
    messages = list(state.get("messages") or [])
    safe_message = str(message or "").strip()
    if safe_message:
        messages.append(safe_message)
    return messages
