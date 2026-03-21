from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_current_user_profile
from models.schemas import (
    CollectionAutoCleanupResponse,
    CollectionCreateRequest,
    CollectionDeleteResponse,
    CollectionItem,
    CollectionListResponse,
    CollectionPaperAttachRequest,
    CollectionPaperAttachResponse,
    CollectionPaperDetachResponse,
    CollectionUpdateRequest,
    SavedPaperCreateRequest,
    SavedPaperDeleteResponse,
    SavedPaperItem,
    SavedPaperListResponse,
    SavedPaperNoteCreateRequest,
    SavedPaperNoteDeleteResponse,
    SavedPaperNoteItem,
    SavedPaperNoteListResponse,
    SavedPaperReadStatus,
    SavedPaperSortBy,
    SavedPaperStatusUpdateRequest,
    SortOrder,
    UserProfile,
)
from services.collection_service import CollectionService, get_collection_service

router = APIRouter(prefix="/api", tags=["collections"])


@router.post("/collections", response_model=CollectionItem)
def create_collection(
    request: CollectionCreateRequest,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> CollectionItem:
    try:
        return collection_service.create_collection(user=user, request=request)
    except ValueError as exc:
        if str(exc) == "collection_name_conflict":
            raise HTTPException(status_code=409, detail="collection_name_conflict") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/collections", response_model=CollectionListResponse)
def list_collections(
    manual_only: bool = Query(default=False),
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> CollectionListResponse:
    return collection_service.list_collections(user=user, manual_only=manual_only)


@router.put("/collections/{collection_id}", response_model=CollectionItem)
def update_collection(
    collection_id: str,
    request: CollectionUpdateRequest,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> CollectionItem:
    try:
        payload = collection_service.update_collection(
            user=user,
            collection_id=collection_id,
            request=request,
        )
    except ValueError as exc:
        if str(exc) == "collection_name_conflict":
            raise HTTPException(status_code=409, detail="collection_name_conflict") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    return payload


@router.delete("/collections/{collection_id}", response_model=CollectionDeleteResponse)
def delete_collection(
    collection_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> CollectionDeleteResponse:
    deleted = collection_service.delete_collection(user=user, collection_id=collection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="collection_not_found")
    return CollectionDeleteResponse(deleted=True)


@router.post("/collections/cleanup-auto", response_model=CollectionAutoCleanupResponse)
def cleanup_auto_generated_content(
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> CollectionAutoCleanupResponse:
    return collection_service.cleanup_auto_generated_content(user=user)


@router.post("/saved-papers", response_model=SavedPaperItem)
def save_paper(
    request: SavedPaperCreateRequest,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperItem:
    try:
        return collection_service.save_paper(user=user, request=request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/saved-papers", response_model=SavedPaperListResponse)
def list_saved_papers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    collection_id: str | None = Query(default=None),
    manual_only: bool = Query(default=False),
    read_status: SavedPaperReadStatus | None = Query(default=None),
    keyword: str | None = Query(default=None),
    sort_by: SavedPaperSortBy = Query(default="saved_at"),
    sort_order: SortOrder = Query(default="desc"),
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperListResponse:
    try:
        return collection_service.list_saved_papers(
            user=user,
            page=page,
            page_size=page_size,
            collection_id=collection_id,
            manual_only=manual_only,
            read_status=read_status,
            keyword=keyword,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/saved-papers/{saved_paper_id}", response_model=SavedPaperDeleteResponse)
def delete_saved_paper(
    saved_paper_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperDeleteResponse:
    deleted = collection_service.delete_saved_paper(user=user, saved_paper_id=saved_paper_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="saved_paper_not_found")
    return SavedPaperDeleteResponse(deleted=True)


@router.patch("/saved-papers/{saved_paper_id}/status", response_model=SavedPaperItem)
def update_saved_paper_status(
    saved_paper_id: str,
    request: SavedPaperStatusUpdateRequest,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperItem:
    try:
        item = collection_service.update_saved_paper_status(
            user=user,
            saved_paper_id=saved_paper_id,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="saved_paper_not_found")
    return item


@router.post("/saved-papers/{saved_paper_id}/enrich-metadata", response_model=SavedPaperItem)
def enrich_saved_paper_metadata(
    saved_paper_id: str,
    force: bool = Query(default=False),
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperItem:
    item = collection_service.enrich_saved_paper_metadata(
        user=user,
        saved_paper_id=saved_paper_id,
        force=force,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="saved_paper_not_found")
    return item


@router.get("/saved-papers/{saved_paper_id}/notes", response_model=SavedPaperNoteListResponse)
def list_saved_paper_notes(
    saved_paper_id: str,
    limit: int = Query(default=30, ge=1, le=100),
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperNoteListResponse:
    try:
        return collection_service.list_saved_paper_notes(
            user=user,
            saved_paper_id=saved_paper_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/saved-papers/{saved_paper_id}/notes", response_model=SavedPaperNoteItem)
def create_saved_paper_note(
    saved_paper_id: str,
    request: SavedPaperNoteCreateRequest,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperNoteItem:
    try:
        return collection_service.create_saved_paper_note(
            user=user,
            saved_paper_id=saved_paper_id,
            request=request,
        )
    except ValueError as exc:
        if str(exc) == "saved_paper_not_found":
            raise HTTPException(status_code=404, detail="saved_paper_not_found") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/saved-papers/{saved_paper_id}/notes/{note_id}",
    response_model=SavedPaperNoteDeleteResponse,
)
def delete_saved_paper_note(
    saved_paper_id: str,
    note_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> SavedPaperNoteDeleteResponse:
    deleted = collection_service.delete_saved_paper_note(
        user=user,
        saved_paper_id=saved_paper_id,
        note_id=note_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="saved_paper_note_not_found")
    return SavedPaperNoteDeleteResponse(deleted=True)


@router.post("/collections/{collection_id}/papers", response_model=CollectionPaperAttachResponse)
def attach_saved_paper_to_collection(
    collection_id: str,
    request: CollectionPaperAttachRequest,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> CollectionPaperAttachResponse:
    linked = collection_service.add_saved_paper_to_collection(
        user=user,
        collection_id=collection_id,
        saved_paper_id=request.saved_paper_id,
    )
    if not linked:
        raise HTTPException(status_code=404, detail="collection_or_saved_paper_not_found")
    return CollectionPaperAttachResponse(linked=True)


@router.delete(
    "/collections/{collection_id}/papers/{saved_paper_id}",
    response_model=CollectionPaperDetachResponse,
)
def detach_saved_paper_from_collection(
    collection_id: str,
    saved_paper_id: str,
    user: UserProfile = Depends(get_current_user_profile),
    collection_service: CollectionService = Depends(get_collection_service),
) -> CollectionPaperDetachResponse:
    unlinked = collection_service.remove_saved_paper_from_collection(
        user=user,
        collection_id=collection_id,
        saved_paper_id=saved_paper_id,
    )
    if not unlinked:
        raise HTTPException(status_code=404, detail="collection_paper_link_not_found")
    return CollectionPaperDetachResponse(unlinked=True)
