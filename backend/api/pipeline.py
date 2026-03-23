from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from api.dependencies import get_current_user_profile
from models.schemas import (
    PipelineReportResponse,
    PipelineResumeRequest,
    PipelineResumeResponse,
    PipelineStartRequest,
    PipelineStartResponse,
    PipelineStopResponse,
    UserProfile,
)
from services.auth_service import AuthService, get_auth_service
from services.pipeline_runtime_service import (
    PipelineRuntimeError,
    get_pipeline_runtime_service,
)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
runtime_service = get_pipeline_runtime_service()


@router.post("/start", response_model=PipelineStartResponse)
async def start_pipeline(
    request: PipelineStartRequest,
    user: UserProfile = Depends(get_current_user_profile),
) -> PipelineStartResponse:
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
    return PipelineStartResponse(session_id=session_id, status="started")


@router.post("/resume/{session_id}", response_model=PipelineResumeResponse)
async def resume_pipeline(
    session_id: str,
    request: PipelineResumeRequest,
    user: UserProfile = Depends(get_current_user_profile),
) -> PipelineResumeResponse:
    resume_feedback = str(request.feedback or "")
    if (
        request.agent_count is not None
        or request.exploration_depth is not None
        or request.agent_mode is not None
    ):
        payload: dict[str, object] = {}
        if resume_feedback.strip():
            payload["feedback"] = resume_feedback
        if request.agent_count is not None:
            payload["agent_count"] = int(request.agent_count)
        if request.exploration_depth is not None:
            payload["exploration_depth"] = int(request.exploration_depth)
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

    return PipelineResumeResponse(resumed=resumed, status=status_text)


@router.post("/stop/{session_id}", response_model=PipelineStopResponse)
async def stop_pipeline(
    session_id: str,
    user: UserProfile = Depends(get_current_user_profile),
) -> PipelineStopResponse:
    try:
        stopped = await runtime_service.stop_session(session_id, user.id)
    except PipelineRuntimeError as exc:
        if str(exc) == "session_not_found":
            raise HTTPException(status_code=404, detail="session_not_found") from exc
        if str(exc) == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PipelineStopResponse(stopped=stopped)


@router.get("/report/{session_id}", response_model=PipelineReportResponse)
async def get_pipeline_report(
    session_id: str,
    user: UserProfile = Depends(get_current_user_profile),
) -> PipelineReportResponse:
    try:
        state, status_text = await runtime_service.get_session_state(session_id, user.id)
    except PipelineRuntimeError as exc:
        if str(exc) == "session_not_found":
            raise HTTPException(status_code=404, detail="session_not_found") from exc
        if str(exc) == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PipelineReportResponse(
        session_id=session_id,
        status=status_text,
        progress=int(state.get("progress") or 0),
        current_node=str(state.get("current_node") or ""),
        research_goal=str(state.get("research_goal") or ""),
        report=state.get("final_report") or state.get("report_draft"),
        report_id=state.get("report_id"),
        errors=[str(item) for item in (state.get("errors") or []) if str(item).strip()],
    )


@router.websocket("/ws/{session_id}")
async def pipeline_websocket(
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
