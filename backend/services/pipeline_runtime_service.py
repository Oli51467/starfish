from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, AsyncGenerator
from uuid import uuid4

from models.schemas import UserProfile
from agents.pipeline.state import PipelineState, build_initial_state

_FINAL_STATUSES = {"completed", "failed", "stopped"}


class PipelineRuntimeError(RuntimeError):
    """Raised when runtime session operation is invalid."""


class PipelineStoppedError(RuntimeError):
    """Raised inside graph nodes when user requests stop."""


@dataclass
class _PipelineSessionRuntime:
    session_id: str
    user_id: str
    state: PipelineState
    status: str = "pending"
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events: list[dict[str, Any]] = field(default_factory=list)
    event_condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[Any] | None = None
    waiting_checkpoint: str | None = None
    resume_event: asyncio.Event | None = None
    resume_feedback: str = ""
    stop_requested: bool = False


class PipelineRuntimeService:
    def __init__(self) -> None:
        self._sessions: dict[str, _PipelineSessionRuntime] = {}
        self._sessions_lock = asyncio.Lock()

    async def start_session(
        self,
        *,
        user: UserProfile,
        input_type: str,
        input_value: str,
        paper_range_years: int | None,
        quick_mode: bool,
    ) -> str:
        session_id = str(uuid4())
        state = build_initial_state(
            session_id=session_id,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
            input_type=input_type,
            input_value=input_value,
            quick_mode=quick_mode,
            paper_range_years=paper_range_years,
        )
        runtime = _PipelineSessionRuntime(
            session_id=session_id,
            user_id=user.id,
            state=state,
            status="pending",
        )

        async with self._sessions_lock:
            self._sessions[session_id] = runtime

        runtime.task = asyncio.create_task(self._run_session(session_id))
        return session_id

    async def _run_session(self, session_id: str) -> None:
        runtime = await self._require_runtime(session_id)
        runtime.status = "running"
        runtime.updated_at = datetime.now(timezone.utc)

        try:
            state = runtime.state
            for node_fn in self._resolve_pipeline_nodes():
                await self.ensure_active(session_id)
                next_state = await node_fn(state)
                if isinstance(next_state, dict):
                    state = next_state
                    runtime.state = next_state
                    runtime.updated_at = datetime.now(timezone.utc)

            if runtime.stop_requested:
                runtime.status = "stopped"
                await self._publish_event(runtime, {
                    "type": "stopped",
                    "message": "流程已停止。",
                })
                return

            runtime.status = "completed"
            runtime.updated_at = datetime.now(timezone.utc)
            await self._publish_event(
                runtime,
                {
                    "type": "session_complete",
                    "progress": int(runtime.state.get("progress") or 100),
                    "current_node": runtime.state.get("current_node") or "parallel",
                    "report_id": runtime.state.get("report_id"),
                    "summary": "研究流程执行完成。",
                },
            )

        except PipelineStoppedError:
            runtime.status = "stopped"
            runtime.updated_at = datetime.now(timezone.utc)
            await self._publish_event(runtime, {
                "type": "stopped",
                "message": "流程已停止。",
            })
        except asyncio.CancelledError:
            runtime.status = "stopped"
            runtime.updated_at = datetime.now(timezone.utc)
            await self._publish_event(runtime, {
                "type": "stopped",
                "message": "流程已停止。",
            })
        except Exception as exc:  # noqa: BLE001
            runtime.status = "failed"
            runtime.updated_at = datetime.now(timezone.utc)
            runtime.error = str(exc)
            state_errors = list(runtime.state.get("errors") or [])
            state_errors.append(str(exc))
            runtime.state["errors"] = state_errors
            await self._publish_event(
                runtime,
                {
                    "type": "error",
                    "message": "Pipeline 执行失败。",
                    "error": str(exc),
                },
            )

    def _resolve_pipeline_nodes(self) -> list:
        from agents.pipeline.nodes.checkpoints import human_checkpoint_1, human_checkpoint_2
        from agents.pipeline.nodes.graph_build import graph_build_node
        from agents.pipeline.nodes.parallel import parallel_analysis_node
        from agents.pipeline.nodes.planner import planner_node
        from agents.pipeline.nodes.router import router_node
        from agents.pipeline.nodes.search import search_node

        return [
            planner_node,
            router_node,
            search_node,
            graph_build_node,
            human_checkpoint_1,
            human_checkpoint_2,
            parallel_analysis_node,
        ]

    async def can_access(self, session_id: str, user_id: str) -> bool:
        runtime = await self._get_runtime(session_id)
        return bool(runtime and runtime.user_id == user_id)

    async def emit_node_start(self, session_id: str, node: str, progress: int) -> None:
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "node_start",
                "node": str(node),
                "progress": int(progress),
            },
        )

    async def emit_thinking(self, session_id: str, node: str, content: str) -> None:
        safe_content = str(content or "").strip()
        if not safe_content:
            return
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "thinking",
                "node": str(node),
                "content": safe_content,
            },
        )

    async def emit_node_complete(
        self,
        session_id: str,
        node: str,
        progress: int,
        summary: str,
    ) -> None:
        runtime = await self._require_runtime(session_id)
        await self._publish_event(
            runtime,
            {
                "type": "node_complete",
                "node": str(node),
                "progress": int(progress),
                "summary": str(summary or ""),
            },
        )

    async def wait_for_checkpoint(
        self,
        session_id: str,
        *,
        checkpoint: str,
        message: str,
        timeout_seconds: int | None = 30,
    ) -> str:
        runtime = await self._require_runtime(session_id)
        await self.ensure_active(session_id)

        runtime.waiting_checkpoint = checkpoint
        runtime.resume_event = asyncio.Event()
        runtime.resume_feedback = ""
        await self._publish_event(
            runtime,
            {
                "type": "pause",
                "checkpoint": checkpoint,
                "message": str(message or ""),
                "timeout": 0 if timeout_seconds is None or int(timeout_seconds) <= 0 else max(1, int(timeout_seconds)),
            },
        )

        try:
            if timeout_seconds is None or int(timeout_seconds) <= 0:
                await runtime.resume_event.wait()
                feedback = runtime.resume_feedback
            else:
                await asyncio.wait_for(runtime.resume_event.wait(), timeout=max(1, int(timeout_seconds)))
                feedback = runtime.resume_feedback
        except TimeoutError:
            feedback = ""
        else:
            if timeout_seconds is None or int(timeout_seconds) <= 0:
                feedback = runtime.resume_feedback
        finally:
            runtime.waiting_checkpoint = None
            runtime.resume_event = None
            runtime.resume_feedback = ""

        if runtime.stop_requested:
            raise PipelineStoppedError("pipeline_stopped")
        return feedback

    async def resume_session(self, session_id: str, user_id: str, feedback: str) -> tuple[bool, str]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        if runtime.status in _FINAL_STATUSES:
            return False, "session_closed"
        if runtime.waiting_checkpoint is None or runtime.resume_event is None:
            return False, "no_pending_checkpoint"

        runtime.resume_feedback = str(feedback or "").strip()
        runtime.resume_event.set()
        await self._publish_event(
            runtime,
            {
                "type": "thinking",
                "node": runtime.waiting_checkpoint,
                "content": "已收到反馈，流程继续执行。",
            },
        )
        return True, "resumed"

    async def stop_session(self, session_id: str, user_id: str) -> bool:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        if runtime.status in _FINAL_STATUSES:
            return False

        runtime.stop_requested = True
        runtime.updated_at = datetime.now(timezone.utc)

        if runtime.resume_event is not None:
            runtime.resume_event.set()
        if runtime.task and not runtime.task.done():
            runtime.task.cancel()
        return True

    async def ensure_active(self, session_id: str) -> None:
        runtime = await self._require_runtime(session_id)
        if runtime.stop_requested:
            raise PipelineStoppedError("pipeline_stopped")

    async def get_session_state(self, session_id: str, user_id: str) -> tuple[PipelineState, str]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        return runtime.state, runtime.status

    async def get_session_snapshot(self, session_id: str, user_id: str) -> dict[str, Any]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")
        return {
            "session_id": runtime.session_id,
            "status": runtime.status,
            "waiting_checkpoint": runtime.waiting_checkpoint or "",
            "state": runtime.state,
            "created_at": runtime.created_at.isoformat(),
            "updated_at": runtime.updated_at.isoformat(),
        }

    async def stream_events(
        self,
        session_id: str,
        user_id: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        runtime = await self._require_runtime(session_id)
        if runtime.user_id != user_id:
            raise PipelineRuntimeError("forbidden")

        cursor = 0
        while True:
            async with runtime.event_condition:
                await runtime.event_condition.wait_for(
                    lambda: cursor < len(runtime.events) or runtime.status in _FINAL_STATUSES
                )
                pending = list(runtime.events[cursor:])
                cursor = len(runtime.events)
                is_final = runtime.status in _FINAL_STATUSES

            for event in pending:
                yield event

            if is_final and cursor >= len(runtime.events):
                break

    async def _publish_event(self, runtime: _PipelineSessionRuntime, event: dict[str, Any]) -> None:
        payload = {
            "session_id": runtime.session_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        runtime.events.append(payload)
        runtime.updated_at = datetime.now(timezone.utc)
        async with runtime.event_condition:
            runtime.event_condition.notify_all()

    async def _get_runtime(self, session_id: str) -> _PipelineSessionRuntime | None:
        async with self._sessions_lock:
            return self._sessions.get(session_id)

    async def _require_runtime(self, session_id: str) -> _PipelineSessionRuntime:
        runtime = await self._get_runtime(session_id)
        if runtime is None:
            raise PipelineRuntimeError("session_not_found")
        return runtime


@lru_cache
def get_pipeline_runtime_service() -> PipelineRuntimeService:
    return PipelineRuntimeService()
