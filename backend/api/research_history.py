from __future__ import annotations

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
    UserProfile,
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
    artifact = insight.get("artifact") if isinstance(insight.get("artifact"), dict) else {}
    raw_path = str(artifact.get(key) or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return None
    return path


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
