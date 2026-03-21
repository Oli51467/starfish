from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from api.dependencies import get_current_user_profile
from models.schemas import (
    ResearchSessionResumeRequest,
    ResearchSessionResumeResponse,
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
    lineage_payload = state.get("lineage_data") if isinstance(state.get("lineage_data"), dict) else None
    report = state.get("final_report") or state.get("report_draft")

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
        lineage=lineage_payload,
        report=str(report) if report is not None else None,
        report_id=str(state.get("report_id") or "").strip() or None,
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


@router.post("/start", response_model=ResearchSessionStartResponse)
async def start_research(
    request: ResearchSessionStartRequest,
    user: UserProfile = Depends(get_current_user_profile),
) -> ResearchSessionStartResponse:
    session_id = await runtime_service.start_session(
        user=user,
        input_type=request.input_type,
        input_value=request.input_value,
        paper_range_years=request.paper_range_years,
        quick_mode=request.quick_mode,
    )
    return ResearchSessionStartResponse(session_id=session_id, status="started")


@router.post("/resume/{session_id}", response_model=ResearchSessionResumeResponse)
async def resume_research(
    session_id: str,
    request: ResearchSessionResumeRequest,
    user: UserProfile = Depends(get_current_user_profile),
) -> ResearchSessionResumeResponse:
    try:
        resumed, status_text = await runtime_service.resume_session(session_id, user.id, request.feedback)
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
