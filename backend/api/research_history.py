from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from api.dependencies import get_current_user_profile
from models.schemas import (
    ResearchHistoryBatchDeleteRequest,
    ResearchHistoryBatchDeleteResponse,
    ResearchHistoryDeleteResponse,
    ResearchHistoryDetailResponse,
    ResearchHistoryListResponse,
    ResearchHistoryReportRegenerateResponse,
    UserProfile,
)
from services.insight_exploration_service import (
    InsightExplorationService,
    get_insight_exploration_service,
)
from services.research_history_service import (
    ResearchHistoryService,
    get_research_history_service,
)

router = APIRouter(prefix="/api/research-history", tags=["research-history"])


def _resolve_history_insight_payload(payload: ResearchHistoryDetailResponse) -> dict:
    pipeline = payload.pipeline if isinstance(payload.pipeline, dict) else {}
    insight = pipeline.get("insight") if isinstance(pipeline.get("insight"), dict) else {}
    return insight


def _resolve_history_artifact_path(insight: dict, *, key: str) -> Path | None:
    raw_path = _resolve_history_artifact_raw_path(insight, key=key)
    if raw_path is None:
        return None
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return None
    return path


def _resolve_history_artifact_raw_path(insight: dict, *, key: str) -> Path | None:
    artifact = insight.get("artifact") if isinstance(insight.get("artifact"), dict) else {}
    raw_path = str(artifact.get(key) or "").strip()
    if not raw_path:
        return None
    return Path(raw_path)


@router.get("", response_model=ResearchHistoryListResponse)
def list_research_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> ResearchHistoryListResponse:
    return history_service.list_history(user=user, page=page, page_size=page_size)


@router.post("/batch-delete", response_model=ResearchHistoryBatchDeleteResponse)
def batch_delete_research_history(
    request: ResearchHistoryBatchDeleteRequest,
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> ResearchHistoryBatchDeleteResponse:
    deleted_ids = history_service.delete_histories(user=user, history_ids=request.history_ids)
    return ResearchHistoryBatchDeleteResponse(
        deleted=bool(deleted_ids),
        deleted_count=len(deleted_ids),
        deleted_ids=deleted_ids,
    )


@router.get("/{history_id}", response_model=ResearchHistoryDetailResponse)
def get_research_history_detail(
    history_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> ResearchHistoryDetailResponse:
    payload = history_service.get_history_detail(user=user, history_id=history_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="research_history_not_found")
    return payload


@router.get("/{history_id}/report/markdown")
def download_research_history_markdown(
    history_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> Response:
    payload = history_service.get_history_detail(user=user, history_id=history_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="research_history_not_found")

    insight = _resolve_history_insight_payload(payload)
    markdown_path = _resolve_history_artifact_path(insight, key="markdown_path")
    if markdown_path is not None:
        return FileResponse(
            path=str(markdown_path),
            media_type="text/markdown; charset=utf-8",
            filename=f"{history_id}-insight.md",
        )

    markdown = str(insight.get("markdown") or "").strip()
    if not markdown:
        markdown = str((payload.pipeline or {}).get("final_report") or "").strip()
    if not markdown:
        raise HTTPException(status_code=404, detail="insight_markdown_not_ready")

    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{history_id}-insight.md"',
        },
    )


@router.get("/{history_id}/report/pdf")
def download_research_history_pdf(
    history_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> FileResponse:
    payload = history_service.get_history_detail(user=user, history_id=history_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="research_history_not_found")

    insight = _resolve_history_insight_payload(payload)
    pdf_path = _resolve_history_artifact_path(insight, key="pdf_path")
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="insight_pdf_not_ready")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{history_id}-insight.pdf",
    )


@router.post("/{history_id}/report/pdf/regenerate", response_model=ResearchHistoryReportRegenerateResponse)
def regenerate_research_history_pdf(
    history_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
    insight_service: InsightExplorationService = Depends(get_insight_exploration_service),
) -> ResearchHistoryReportRegenerateResponse:
    payload = history_service.get_history_detail(user=user, history_id=history_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="research_history_not_found")

    insight = _resolve_history_insight_payload(payload)
    pipeline = payload.pipeline if isinstance(payload.pipeline, dict) else {}
    markdown_path = _resolve_history_artifact_path(insight, key="markdown_path")
    markdown = ""
    if markdown_path is not None:
        try:
            markdown = markdown_path.read_text(encoding="utf-8").strip()
        except OSError:
            markdown = ""
    if not markdown:
        markdown = str(insight.get("markdown") or "").strip()
    if not markdown:
        markdown = str(pipeline.get("final_report") or "").strip()
    if not markdown:
        raise HTTPException(status_code=404, detail="insight_markdown_not_ready")

    language = str(insight.get("language") or "").strip().lower()
    if language not in {"zh", "en"}:
        language = "zh"

    raw_pdf_path = _resolve_history_artifact_raw_path(insight, key="pdf_path")
    if raw_pdf_path is not None:
        target_pdf_path = raw_pdf_path
    else:
        raw_markdown_path = _resolve_history_artifact_raw_path(insight, key="markdown_path")
        if raw_markdown_path is not None:
            target_pdf_path = raw_markdown_path.with_suffix(".pdf")
        else:
            target_pdf_path = insight_service.report_root / f"history-{history_id}" / "insight.pdf"

    try:
        regenerated_pdf_path = insight_service.render_markdown_pdf(
            markdown=markdown,
            pdf_path=target_pdf_path,
            language=language,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="insight_pdf_regenerate_failed") from exc

    existing_artifact = insight.get("artifact") if isinstance(insight.get("artifact"), dict) else {}
    updated_artifact = dict(existing_artifact)
    updated_artifact["pdf_path"] = str(regenerated_pdf_path)

    updated_insight = dict(insight)
    updated_insight["artifact"] = updated_artifact
    if not str(updated_insight.get("language") or "").strip():
        updated_insight["language"] = language
    if not str(updated_insight.get("markdown") or "").strip():
        updated_insight["markdown"] = markdown
    updated_insight["updated_at"] = datetime.now(timezone.utc).isoformat()

    updated_pipeline = dict(pipeline)
    updated_pipeline["insight"] = updated_insight
    persisted = history_service.update_pipeline_payload(
        user=user,
        history_id=history_id,
        pipeline_payload=updated_pipeline,
    )
    if not persisted:
        raise HTTPException(status_code=500, detail="insight_pdf_path_persist_failed")

    return ResearchHistoryReportRegenerateResponse(
        history_id=history_id,
        regenerated=True,
        pdf_path=str(regenerated_pdf_path),
    )


@router.delete("/{history_id}", response_model=ResearchHistoryDeleteResponse)
def delete_research_history(
    history_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    history_service: ResearchHistoryService = Depends(get_research_history_service),
) -> ResearchHistoryDeleteResponse:
    deleted = history_service.delete_history(user=user, history_id=history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="research_history_not_found")
    return ResearchHistoryDeleteResponse(deleted=True)
