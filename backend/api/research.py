from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse

from api.dependencies import get_current_user_profile
from models.schemas import (
    ResearchActiveSessionResponse,
    ResearchSessionResumeRequest,
    ResearchSessionResumeResponse,
    ResearchActiveSessionSummary,
    ResearchSessionStartRequest,
    ResearchSessionStartResponse,
    ResearchSessionStateResponse,
    ResearchSessionStopResponse,
    UserProfile,
)
from services.auth_service import AuthService, get_auth_service
from services.pipeline_runtime_service import (
    PipelineRuntimeError,
    get_pipeline_runtime_service,
)

router = APIRouter(prefix="/api/research", tags=["research"])
runtime_service = get_pipeline_runtime_service()


def _to_safe_input_type(raw_value: object) -> str:
    safe = str(raw_value or "").strip().lower()
    if safe in {"domain", "doi"}:
        return safe
    return "arxiv_id"


def _to_state_response(snapshot: dict) -> ResearchSessionStateResponse:
    state = snapshot.get("state") or {}
    graph_payload = state.get("graph_payload") if isinstance(state.get("graph_payload"), dict) else None
    report = state.get("final_report") or state.get("report_draft")
    insight_payload = state.get("insight") if isinstance(state.get("insight"), dict) else None

    return ResearchSessionStateResponse(
        session_id=str(snapshot.get("session_id") or ""),
        status=str(snapshot.get("status") or "pending"),
        progress=int(state.get("progress") or 0),
        current_node=str(state.get("current_node") or ""),
        waiting_checkpoint=str(snapshot.get("waiting_checkpoint") or ""),
        input_type=_to_safe_input_type(state.get("input_type")),
        input_value=str(state.get("input_value") or ""),
        paper_range_years=state.get("paper_range_years"),
        quick_mode=bool(state.get("quick_mode")),
        research_goal=str(state.get("research_goal") or ""),
        execution_plan=[str(item) for item in (state.get("execution_plan") or []) if str(item).strip()],
        checkpoint_feedback={
            str(key): str(value)
            for key, value in dict(state.get("checkpoint_feedback") or {}).items()
            if str(key).strip()
        },
        graph=graph_payload,
        lineage=None,
        report=str(report) if report is not None else None,
        report_id=str(state.get("report_id") or "").strip() or None,
        insight=insight_payload,
        history_id=str(state.get("history_id") or "").strip() or None,
        research_gaps=[
            item for item in (state.get("research_gaps") or [])
            if isinstance(item, dict)
        ],
        critic_notes=[str(item) for item in (state.get("critic_notes") or []) if str(item).strip()],
        papers=[item for item in (state.get("papers") or []) if isinstance(item, dict)],
        errors=[str(item) for item in (state.get("errors") or []) if str(item).strip()],
        messages=[str(item) for item in (state.get("messages") or []) if str(item).strip()],
    )


def _resolve_insight_artifact_path(snapshot: dict, *, artifact_key: str) -> Path | None:
    state = snapshot.get("state") or {}
    insight = state.get("insight")
    if not isinstance(insight, dict):
        return None
    artifact = insight.get("artifact")
    if not isinstance(artifact, dict):
        return None
    raw_path = str(artifact.get(artifact_key) or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return None
    return path


def _to_active_session_summary(snapshot: dict) -> ResearchActiveSessionSummary:
    state = snapshot.get("state") or {}
    return ResearchActiveSessionSummary(
        session_id=str(snapshot.get("session_id") or ""),
        status=str(snapshot.get("status") or "pending"),
        progress=int(state.get("progress") or 0),
        current_node=str(state.get("current_node") or ""),
        waiting_checkpoint=str(snapshot.get("waiting_checkpoint") or ""),
        input_type=_to_safe_input_type(state.get("input_type")),
        input_value=str(state.get("input_value") or ""),
        paper_range_years=state.get("paper_range_years"),
        quick_mode=bool(state.get("quick_mode")),
        updated_at=str(snapshot.get("updated_at") or ""),
    )


@router.post("/start", response_model=ResearchSessionStartResponse)
async def start_research(
    request: ResearchSessionStartRequest,
    user: UserProfile = Depends(get_current_user_profile),
) -> ResearchSessionStartResponse:
    try:
        session_id = await runtime_service.start_session(
            user=user,
            input_type=request.input_type,
            input_value=request.input_value,
            paper_range_years=request.paper_range_years,
            quick_mode=request.quick_mode,
        )
    except PipelineRuntimeError as exc:
        detail = str(exc)
        if detail.startswith("active_session_exists:"):
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return ResearchSessionStartResponse(session_id=session_id, status="started")


@router.get("/active", response_model=ResearchActiveSessionResponse)
async def get_active_research_session(
    user: UserProfile = Depends(get_current_user_profile),
) -> ResearchActiveSessionResponse:
    snapshot = await runtime_service.get_active_session_snapshot(user.id)
    if not isinstance(snapshot, dict):
        return ResearchActiveSessionResponse(has_active_session=False, session=None)
    return ResearchActiveSessionResponse(
        has_active_session=True,
        session=_to_active_session_summary(snapshot),
    )


@router.post("/resume/{session_id}", response_model=ResearchSessionResumeResponse)
async def resume_research(
    session_id: str,
    request: ResearchSessionResumeRequest,
    user: UserProfile = Depends(get_current_user_profile),
) -> ResearchSessionResumeResponse:
    resume_feedback = str(request.feedback or "")
    if (
        request.agent_count is not None
        or request.exploration_depth is not None
        or request.report_language is not None
        or request.agent_mode is not None
    ):
        payload: dict[str, object] = {}
        if resume_feedback.strip():
            payload["feedback"] = resume_feedback
        if request.agent_count is not None:
            payload["agent_count"] = int(request.agent_count)
        if request.exploration_depth is not None:
            payload["exploration_depth"] = int(request.exploration_depth)
        if request.report_language is not None:
            payload["report_language"] = str(request.report_language).strip().lower()
        if request.agent_mode is not None:
            payload["agent_mode"] = str(request.agent_mode)
        resume_feedback = json.dumps(payload, ensure_ascii=False)

    try:
        resumed, status_text = await runtime_service.resume_session(session_id, user.id, resume_feedback)
    except PipelineRuntimeError as exc:
        if str(exc) == "session_not_found":
            raise HTTPException(status_code=404, detail="session_not_found") from exc
        if str(exc) == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResearchSessionResumeResponse(resumed=resumed, status=status_text)


@router.post("/stop/{session_id}", response_model=ResearchSessionStopResponse)
async def stop_research(
    session_id: str,
    user: UserProfile = Depends(get_current_user_profile),
) -> ResearchSessionStopResponse:
    try:
        stopped = await runtime_service.stop_session(session_id, user.id)
    except PipelineRuntimeError as exc:
        if str(exc) == "session_not_found":
            raise HTTPException(status_code=404, detail="session_not_found") from exc
        if str(exc) == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResearchSessionStopResponse(stopped=stopped)


@router.get("/session/{session_id}", response_model=ResearchSessionStateResponse)
async def get_research_session(
    session_id: str,
    user: UserProfile = Depends(get_current_user_profile),
) -> ResearchSessionStateResponse:
    try:
        snapshot = await runtime_service.get_session_snapshot(session_id, user.id)
    except PipelineRuntimeError as exc:
        if str(exc) == "session_not_found":
            raise HTTPException(status_code=404, detail="session_not_found") from exc
        if str(exc) == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_state_response(snapshot)


@router.get("/report/{session_id}/markdown")
async def download_research_report_markdown(
    session_id: str,
    user: UserProfile = Depends(get_current_user_profile),
) -> FileResponse:
    try:
        snapshot = await runtime_service.get_session_snapshot(session_id, user.id)
    except PipelineRuntimeError as exc:
        if str(exc) == "session_not_found":
            raise HTTPException(status_code=404, detail="session_not_found") from exc
        if str(exc) == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = _resolve_insight_artifact_path(snapshot, artifact_key="markdown_path")
    if path is None:
        raise HTTPException(status_code=404, detail="insight_markdown_not_ready")

    return FileResponse(
        path=str(path),
        media_type="text/markdown; charset=utf-8",
        filename=f"{session_id}-insight.md",
    )


@router.get("/report/{session_id}/pdf")
async def download_research_report_pdf(
    session_id: str,
    user: UserProfile = Depends(get_current_user_profile),
) -> FileResponse:
    try:
        snapshot = await runtime_service.get_session_snapshot(session_id, user.id)
    except PipelineRuntimeError as exc:
        if str(exc) == "session_not_found":
            raise HTTPException(status_code=404, detail="session_not_found") from exc
        if str(exc) == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = _resolve_insight_artifact_path(snapshot, artifact_key="pdf_path")
    if path is None:
        raise HTTPException(status_code=404, detail="insight_pdf_not_ready")

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=f"{session_id}-insight.pdf",
    )


@router.websocket("/ws/{session_id}")
async def research_websocket(
    ws: WebSocket,
    session_id: str,
    token: str = Query(default=""),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    try:
        user = auth_service.verify_session_token(token)
    except HTTPException:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    can_access = await runtime_service.can_access(session_id, user.id)
    if not can_access:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()
    try:
        async for event in runtime_service.stream_events(session_id, user.id):
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    except PipelineRuntimeError:
        await ws.close(code=status.WS_1011_INTERNAL_ERROR)
