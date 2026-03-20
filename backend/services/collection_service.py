from __future__ import annotations

from functools import lru_cache
import math
import re
from typing import Any

from external.openalex import OpenAlexClient, OpenAlexClientError
from external.semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarClientError,
    SemanticScholarNotFoundError,
)
from models.schemas import (
    CollectionCreateRequest,
    CollectionItem,
    CollectionListResponse,
    CollectionUpdateRequest,
    SavedPaperCreateRequest,
    SavedPaperItem,
    SavedPaperListResponse,
    SavedPaperMetadata,
    SavedPaperNoteCreateRequest,
    SavedPaperNoteItem,
    SavedPaperNoteListResponse,
    SavedPaperStatusUpdateRequest,
    UserProfile,
)
from repositories.collection_repository import CollectionRepository, get_collection_repository

_VALID_READ_STATUS = {"unread", "reading", "completed"}
_VALID_SORT_BY = {"saved_at", "last_opened_at", "year", "citation_count"}
_VALID_SORT_ORDER = {"asc", "desc"}
_DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
_ARXIV_PATTERN = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[a-z\-]+)?/\d{7})(?:v\d+)?$",
    re.IGNORECASE,
)
_UNKNOWN_VENUE = "Unknown Venue"


class CollectionService:
    def __init__(
        self,
        repository: CollectionRepository | None = None,
        semantic_client: SemanticScholarClient | None = None,
        openalex_client: OpenAlexClient | None = None,
    ) -> None:
        self.repository = repository or get_collection_repository()
        self.semantic_client = semantic_client or SemanticScholarClient()
        self.openalex_client = openalex_client or OpenAlexClient()

    def create_collection(self, *, user: UserProfile, request: CollectionCreateRequest) -> CollectionItem:
        name = str(request.name or "").strip()
        if not name:
            raise ValueError("collection_name_required")
        row = self.repository.create_collection(
            user_id=user.id,
            name=name,
            color=str(request.color or "").strip(),
            emoji=str(request.emoji or "").strip(),
        )
        return self._to_collection_item(row)

    def list_collections(self, *, user: UserProfile) -> CollectionListResponse:
        rows = self.repository.list_collections(user_id=user.id)
        return CollectionListResponse(items=[self._to_collection_item(row) for row in rows])

    def update_collection(
        self,
        *,
        user: UserProfile,
        collection_id: str,
        request: CollectionUpdateRequest,
    ) -> CollectionItem | None:
        safe_collection_id = str(collection_id or "").strip()
        if not safe_collection_id:
            return None

        safe_name = str(request.name).strip() if request.name is not None else None
        if safe_name is not None and not safe_name:
            raise ValueError("collection_name_required")

        safe_color = str(request.color or "").strip() if request.color is not None else None
        safe_emoji = str(request.emoji or "").strip() if request.emoji is not None else None

        row = self.repository.update_collection(
            user_id=user.id,
            collection_id=safe_collection_id,
            name=safe_name,
            color=safe_color,
            emoji=safe_emoji,
        )
        if row is None:
            return None
        return self._to_collection_item(row)

    def delete_collection(self, *, user: UserProfile, collection_id: str) -> bool:
        return self.repository.delete_collection(
            user_id=user.id,
            collection_id=str(collection_id or "").strip(),
        )

    def save_paper(self, *, user: UserProfile, request: SavedPaperCreateRequest) -> SavedPaperItem:
        paper_id = str(request.paper_id or "").strip()
        if not paper_id:
            raise ValueError("paper_id_required")

        metadata = self._normalize_metadata(request.metadata)
        if self._needs_metadata_enrichment(metadata):
            metadata = self._enrich_metadata_payload(
                paper_id=paper_id,
                current_payload=metadata,
            )
        row, _ = self.repository.create_or_get_saved_paper(
            user_id=user.id,
            paper_id=paper_id,
            paper_payload=metadata,
        )
        saved_paper_id = str(row.get("id") or "").strip()
        if not saved_paper_id:
            raise RuntimeError("saved_paper_create_failed")

        unique_collection_ids: list[str] = []
        seen: set[str] = set()
        for item in request.collection_ids or []:
            safe_collection_id = str(item or "").strip()
            if not safe_collection_id or safe_collection_id in seen:
                continue
            seen.add(safe_collection_id)
            unique_collection_ids.append(safe_collection_id)

        for collection_id in unique_collection_ids:
            linked = self.repository.attach_saved_paper_to_collection(
                user_id=user.id,
                collection_id=collection_id,
                saved_paper_id=saved_paper_id,
            )
            if not linked:
                raise LookupError("collection_not_found")

        collection_map = self.repository.list_collection_ids_for_saved_papers(saved_paper_ids=[saved_paper_id])
        row["collection_ids"] = collection_map.get(saved_paper_id, [])
        return self._to_saved_paper_item(row)

    def list_saved_papers(
        self,
        *,
        user: UserProfile,
        page: int,
        page_size: int,
        collection_id: str | None = None,
        read_status: str | None = None,
        keyword: str | None = None,
        sort_by: str = "saved_at",
        sort_order: str = "desc",
    ) -> SavedPaperListResponse:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(50, int(page_size)))
        safe_sort_by = str(sort_by or "saved_at").strip().lower()
        if safe_sort_by not in _VALID_SORT_BY:
            safe_sort_by = "saved_at"
        safe_sort_order = str(sort_order or "desc").strip().lower()
        if safe_sort_order not in _VALID_SORT_ORDER:
            safe_sort_order = "desc"

        safe_read_status = str(read_status or "").strip().lower()
        if safe_read_status and safe_read_status not in _VALID_READ_STATUS:
            raise ValueError("invalid_read_status")

        rows, total = self.repository.list_saved_papers(
            user_id=user.id,
            page=safe_page,
            page_size=safe_page_size,
            collection_id=str(collection_id or "").strip() or None,
            read_status=safe_read_status or None,
            keyword=str(keyword or "").strip() or None,
            sort_by=safe_sort_by,
            sort_order=safe_sort_order,
        )
        total_pages = (total + safe_page_size - 1) // safe_page_size if total > 0 else 0
        return SavedPaperListResponse(
            page=safe_page,
            page_size=safe_page_size,
            total=total,
            total_pages=total_pages,
            items=[self._to_saved_paper_item(row) for row in rows],
        )

    def delete_saved_paper(self, *, user: UserProfile, saved_paper_id: str) -> bool:
        return self.repository.delete_saved_paper(
            user_id=user.id,
            saved_paper_id=str(saved_paper_id or "").strip(),
        )

    def update_saved_paper_status(
        self,
        *,
        user: UserProfile,
        saved_paper_id: str,
        request: SavedPaperStatusUpdateRequest,
    ) -> SavedPaperItem | None:
        safe_status = str(request.read_status or "").strip().lower()
        if safe_status not in _VALID_READ_STATUS:
            raise ValueError("invalid_read_status")

        row = self.repository.update_saved_paper_status(
            user_id=user.id,
            saved_paper_id=str(saved_paper_id or "").strip(),
            read_status=safe_status,
            touch_last_opened=bool(request.touch_last_opened),
        )
        if row is None:
            return None

        saved_id = str(row.get("id") or "").strip()
        collection_map = self.repository.list_collection_ids_for_saved_papers(saved_paper_ids=[saved_id])
        row["collection_ids"] = collection_map.get(saved_id, [])
        return self._to_saved_paper_item(row)

    def enrich_saved_paper_metadata(
        self,
        *,
        user: UserProfile,
        saved_paper_id: str,
        force: bool = False,
    ) -> SavedPaperItem | None:
        safe_saved_paper_id = str(saved_paper_id or "").strip()
        if not safe_saved_paper_id:
            return None

        row = self.repository.get_saved_paper(
            user_id=user.id,
            saved_paper_id=safe_saved_paper_id,
        )
        if row is None:
            return None

        current_payload = self._normalize_metadata_payload_dict(row.get("paper_payload"))
        next_payload = dict(current_payload)
        if force or self._needs_metadata_enrichment(current_payload):
            next_payload = self._enrich_metadata_payload(
                paper_id=str(row.get("paper_id") or "").strip(),
                current_payload=current_payload,
            )
            if next_payload != current_payload:
                updated_row = self.repository.update_saved_paper_payload(
                    user_id=user.id,
                    saved_paper_id=safe_saved_paper_id,
                    paper_payload=next_payload,
                )
                if updated_row is not None:
                    row = updated_row

        row["paper_payload"] = next_payload
        collection_map = self.repository.list_collection_ids_for_saved_papers(
            saved_paper_ids=[safe_saved_paper_id]
        )
        row["collection_ids"] = collection_map.get(safe_saved_paper_id, [])
        return self._to_saved_paper_item(row)

    def list_saved_paper_notes(
        self,
        *,
        user: UserProfile,
        saved_paper_id: str,
        limit: int = 30,
    ) -> SavedPaperNoteListResponse:
        safe_saved_paper_id = str(saved_paper_id or "").strip()
        if not safe_saved_paper_id:
            raise ValueError("saved_paper_id_required")
        rows = self.repository.list_saved_paper_notes(
            user_id=user.id,
            saved_paper_id=safe_saved_paper_id,
            limit=limit,
        )
        return SavedPaperNoteListResponse(
            items=[self._to_saved_paper_note_item(row) for row in rows]
        )

    def create_saved_paper_note(
        self,
        *,
        user: UserProfile,
        saved_paper_id: str,
        request: SavedPaperNoteCreateRequest,
    ) -> SavedPaperNoteItem:
        safe_saved_paper_id = str(saved_paper_id or "").strip()
        safe_content = str(request.content or "").strip()
        if not safe_saved_paper_id:
            raise ValueError("saved_paper_id_required")
        if not safe_content:
            raise ValueError("note_content_required")

        row = self.repository.create_saved_paper_note(
            user_id=user.id,
            saved_paper_id=safe_saved_paper_id,
            content=safe_content,
        )
        if row is None:
            raise ValueError("saved_paper_not_found")
        return self._to_saved_paper_note_item(row)

    def delete_saved_paper_note(
        self,
        *,
        user: UserProfile,
        saved_paper_id: str,
        note_id: str,
    ) -> bool:
        return self.repository.delete_saved_paper_note(
            user_id=user.id,
            saved_paper_id=str(saved_paper_id or "").strip(),
            note_id=str(note_id or "").strip(),
        )

    def add_saved_paper_to_collection(
        self,
        *,
        user: UserProfile,
        collection_id: str,
        saved_paper_id: str,
    ) -> bool:
        return self.repository.attach_saved_paper_to_collection(
            user_id=user.id,
            collection_id=str(collection_id or "").strip(),
            saved_paper_id=str(saved_paper_id or "").strip(),
        )

    def remove_saved_paper_from_collection(
        self,
        *,
        user: UserProfile,
        collection_id: str,
        saved_paper_id: str,
    ) -> bool:
        return self.repository.detach_saved_paper_from_collection(
            user_id=user.id,
            collection_id=str(collection_id or "").strip(),
            saved_paper_id=str(saved_paper_id or "").strip(),
        )

    def _enrich_metadata_payload(
        self,
        *,
        paper_id: str,
        current_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = self._normalize_metadata_payload_dict(current_payload)
        paper_id_text = str(paper_id or "").strip()

        for candidate in self._fetch_external_metadata_candidates(
            paper_id=paper_id_text,
            title_hint=str(merged.get("title") or "").strip(),
        ):
            merged = self._merge_metadata_payload(base=merged, incoming=candidate)
            if not self._needs_metadata_enrichment(merged):
                break

        if merged.get("impact_factor") is None:
            estimated_impact = self._estimate_impact_factor(
                self._safe_int(merged.get("citation_count"))
            )
            if estimated_impact is not None:
                merged["impact_factor"] = estimated_impact

        return self._normalize_metadata_payload_dict(merged)

    def _fetch_external_metadata_candidates(
        self,
        *,
        paper_id: str,
        title_hint: str,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        def add_candidate(payload: dict[str, Any] | None) -> None:
            normalized = self._normalize_external_metadata(payload)
            if not normalized:
                return
            dedup_key = self._metadata_dedup_key(normalized)
            if dedup_key and dedup_key in seen_keys:
                return
            if dedup_key:
                seen_keys.add(dedup_key)
            candidates.append(normalized)

        safe_paper_id = str(paper_id or "").strip()
        arxiv_id = self._extract_arxiv_id(safe_paper_id)
        doi = self._extract_doi(safe_paper_id)

        if safe_paper_id:
            add_candidate(
                self._safe_fetch_semantic_paper(
                    safe_paper_id,
                    reference_limit=1,
                    citation_limit=1,
                )
            )
            if safe_paper_id.lower().startswith("openalex:"):
                add_candidate(
                    self._safe_fetch_openalex_paper(
                        safe_paper_id,
                        reference_limit=1,
                        citation_limit=1,
                    )
                )

        if arxiv_id:
            add_candidate(
                self._safe_fetch_semantic_by_arxiv_id(
                    arxiv_id,
                    reference_limit=1,
                    citation_limit=1,
                )
            )
            add_candidate(
                self._safe_fetch_openalex_by_arxiv_id(
                    arxiv_id,
                    reference_limit=1,
                    citation_limit=1,
                )
            )

        if doi:
            add_candidate(
                self._safe_fetch_semantic_by_doi(
                    doi,
                    reference_limit=1,
                    citation_limit=1,
                )
            )
            add_candidate(
                self._safe_fetch_openalex_by_doi(
                    doi,
                    reference_limit=1,
                    citation_limit=1,
                )
            )

        safe_title = str(title_hint or "").strip()
        if safe_title and len(safe_title) >= 8:
            add_candidate(self._safe_search_semantic_first(safe_title))
            add_candidate(self._safe_search_openalex_first(safe_title))

        return candidates

    def _safe_fetch_semantic_paper(
        self,
        paper_id: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        try:
            return self.semantic_client.fetch_paper(
                paper_id,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        except (SemanticScholarNotFoundError, SemanticScholarClientError, ValueError):
            return None

    def _safe_fetch_semantic_by_arxiv_id(
        self,
        arxiv_id: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        try:
            return self.semantic_client.fetch_paper_by_arxiv_id(
                arxiv_id,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        except (SemanticScholarNotFoundError, SemanticScholarClientError, ValueError):
            return None

    def _safe_fetch_semantic_by_doi(
        self,
        doi: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        try:
            return self.semantic_client.fetch_paper_by_doi(
                doi,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        except (SemanticScholarNotFoundError, SemanticScholarClientError, ValueError):
            return None

    def _safe_fetch_openalex_paper(
        self,
        paper_id: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        try:
            return self.openalex_client.fetch_paper(
                paper_id,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        except OpenAlexClientError:
            return None

    def _safe_fetch_openalex_by_arxiv_id(
        self,
        arxiv_id: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        try:
            return self.openalex_client.fetch_paper_by_arxiv_id(
                arxiv_id,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        except OpenAlexClientError:
            return None

    def _safe_fetch_openalex_by_doi(
        self,
        doi: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        try:
            return self.openalex_client.fetch_paper_by_doi(
                doi,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        except OpenAlexClientError:
            return None

    def _safe_search_semantic_first(self, query: str) -> dict[str, Any] | None:
        try:
            payload = self.semantic_client.search_papers(query=query, limit=1, offset=0)
        except (SemanticScholarClientError, ValueError):
            return None
        papers = payload.get("papers") if isinstance(payload, dict) else []
        if not papers:
            return None
        first = papers[0]
        return first if isinstance(first, dict) else None

    def _safe_search_openalex_first(self, query: str) -> dict[str, Any] | None:
        try:
            payload = self.openalex_client.search_papers(query=query, limit=1, offset=0)
        except OpenAlexClientError:
            return None
        papers = payload.get("papers") if isinstance(payload, dict) else []
        if not papers:
            return None
        first = papers[0]
        return first if isinstance(first, dict) else None

    def _normalize_external_metadata(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        normalized = self._normalize_metadata_payload_dict(payload)
        if (
            not normalized.get("title")
            and not normalized.get("authors")
            and not normalized.get("fields_of_study")
            and not normalized.get("citation_count")
        ):
            return {}
        return normalized

    @staticmethod
    def _metadata_dedup_key(payload: dict[str, Any]) -> str:
        title = str(payload.get("title") or "").strip().lower()
        year = CollectionService._safe_int_or_none(payload.get("year"))
        paper_url = str(payload.get("url") or "").strip().lower()
        if title and year:
            return f"{title}:{year}"
        if title:
            return title
        return paper_url

    @classmethod
    def _merge_metadata_payload(
        cls,
        *,
        base: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        merged = cls._normalize_metadata_payload_dict(base)
        candidate = cls._normalize_metadata_payload_dict(incoming)
        if not candidate:
            return merged

        for key in ("title", "abstract", "publication_date", "url"):
            if not str(merged.get(key) or "").strip():
                merged[key] = str(candidate.get(key) or "").strip()

        base_venue = str(merged.get("venue") or "").strip()
        incoming_venue = str(candidate.get("venue") or "").strip()
        if (
            (not base_venue or base_venue.lower() == _UNKNOWN_VENUE.lower())
            and incoming_venue
            and incoming_venue.lower() != _UNKNOWN_VENUE.lower()
        ):
            merged["venue"] = incoming_venue

        merged["year"] = cls._prefer_positive_int(merged.get("year"), candidate.get("year"))
        merged["citation_count"] = max(
            cls._safe_int(merged.get("citation_count")),
            cls._safe_int(candidate.get("citation_count")),
        )
        if merged.get("impact_factor") is None and candidate.get("impact_factor") is not None:
            merged["impact_factor"] = candidate.get("impact_factor")

        merged["authors"] = cls._merge_unique_texts(
            merged.get("authors"),
            candidate.get("authors"),
            limit=12,
        )
        merged["fields_of_study"] = cls._merge_unique_texts(
            merged.get("fields_of_study"),
            candidate.get("fields_of_study"),
            limit=8,
        )

        return cls._normalize_metadata_payload_dict(merged)

    @classmethod
    def _normalize_metadata_payload_dict(cls, payload: Any) -> dict[str, Any]:
        raw_payload = payload if isinstance(payload, dict) else {}
        authors = cls._normalize_text_list(raw_payload.get("authors"), max_size=12)

        year = cls._safe_int_or_none(
            raw_payload.get("year")
            if raw_payload.get("year") is not None
            else raw_payload.get("publicationYear")
        )

        citation_count = cls._safe_int(
            raw_payload.get("citation_count")
            if raw_payload.get("citation_count") is not None
            else raw_payload.get("citationCount")
        )

        raw_impact = (
            raw_payload.get("impact_factor")
            if raw_payload.get("impact_factor") is not None
            else raw_payload.get("impactFactor")
        )
        impact_factor = cls._safe_nonnegative_float_or_none(raw_impact)

        fields_source = (
            raw_payload.get("fields_of_study")
            if raw_payload.get("fields_of_study") is not None
            else raw_payload.get("fieldsOfStudy")
        )
        fields_of_study = cls._normalize_text_list(fields_source, max_size=8)

        publication_date = str(
            raw_payload.get("publication_date")
            or raw_payload.get("publicationDate")
            or ""
        ).strip()
        venue = str(raw_payload.get("venue") or "").strip()
        url = str(raw_payload.get("url") or "").strip()

        return {
            "title": str(raw_payload.get("title") or "").strip(),
            "abstract": str(raw_payload.get("abstract") or "").strip(),
            "authors": authors,
            "year": year,
            "publication_date": publication_date,
            "citation_count": citation_count,
            "impact_factor": impact_factor,
            "fields_of_study": fields_of_study,
            "venue": venue,
            "url": url or None,
        }

    @staticmethod
    def _needs_metadata_enrichment(payload: dict[str, Any] | None) -> bool:
        normalized = CollectionService._normalize_metadata_payload_dict(payload)
        impact_factor_missing = normalized.get("impact_factor") is None
        fields_missing = not normalized.get("fields_of_study")
        return impact_factor_missing or fields_missing

    @classmethod
    def _extract_doi(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.lower().startswith("doi:"):
            text = text.split(":", 1)[1]
        match = _DOI_PATTERN.search(text)
        if not match:
            return ""
        return match.group(0).lower().rstrip(").,;")

    @staticmethod
    def _extract_arxiv_id(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        if lowered.startswith("arxiv:"):
            candidate = text.split(":", 1)[1].strip()
            return candidate
        if lowered.startswith("10.48550/arxiv."):
            return re.sub(r"^10\.48550/arxiv\.", "", text, flags=re.IGNORECASE).strip()
        if _ARXIV_PATTERN.match(text):
            return text
        return ""

    @staticmethod
    def _estimate_impact_factor(citation_count: int) -> float | None:
        safe_citations = max(0, int(citation_count or 0))
        if safe_citations <= 0:
            return None
        if safe_citations >= 5000:
            return 15.8
        if safe_citations >= 1200:
            return 12.4
        if safe_citations >= 400:
            return 8.9
        if safe_citations >= 150:
            return 5.6
        if safe_citations >= 50:
            return 3.6
        influence = min(1.0, math.log1p(safe_citations) / math.log1p(50))
        return round(1.8 + influence * 1.4, 1)

    @staticmethod
    def _safe_int(raw_value: Any) -> int:
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_int_or_none(raw_value: Any) -> int | None:
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _safe_nonnegative_float_or_none(raw_value: Any) -> float | None:
        try:
            parsed = float(raw_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed) or parsed < 0:
            return None
        return parsed

    @staticmethod
    def _normalize_text_list(raw_values: Any, *, max_size: int) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        if isinstance(raw_values, str):
            raw_iterable = re.split(r"[;,，\n]+", raw_values)
        elif isinstance(raw_values, list):
            raw_iterable = raw_values
        else:
            raw_iterable = []
        for raw in raw_iterable:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(text)
            if len(items) >= max(1, max_size):
                break
        return items

    @staticmethod
    def _merge_unique_texts(left: Any, right: Any, *, limit: int) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for raw in [*(left or []), *(right or [])]:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(text)
            if len(merged) >= max(1, limit):
                break
        return merged

    @staticmethod
    def _prefer_positive_int(left: Any, right: Any) -> int | None:
        left_val = CollectionService._safe_int_or_none(left)
        right_val = CollectionService._safe_int_or_none(right)
        if left_val and right_val:
            return max(left_val, right_val)
        return left_val or right_val

    @staticmethod
    def _normalize_metadata(metadata: SavedPaperMetadata | None) -> dict[str, Any]:
        if metadata is None:
            return {}
        payload = {
            "title": metadata.title,
            "abstract": metadata.abstract,
            "authors": metadata.authors,
            "year": metadata.year,
            "publication_date": metadata.publication_date,
            "citation_count": metadata.citation_count,
            "impact_factor": metadata.impact_factor,
            "fields_of_study": metadata.fields_of_study,
            "venue": metadata.venue,
            "url": metadata.url,
        }
        return CollectionService._normalize_metadata_payload_dict(payload)

    @staticmethod
    def _to_collection_item(row: dict[str, Any]) -> CollectionItem:
        return CollectionItem(
            collection_id=str(row.get("id") or ""),
            name=str(row.get("name") or ""),
            color=str(row.get("color") or ""),
            emoji=str(row.get("emoji") or ""),
            paper_count=max(0, int(row.get("paper_count") or 0)),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    @staticmethod
    def _to_saved_paper_item(row: dict[str, Any]) -> SavedPaperItem:
        payload = CollectionService._normalize_metadata_payload_dict(row.get("paper_payload"))
        authors = [str(item) for item in (payload.get("authors") or []) if str(item).strip()]
        read_status = str(row.get("read_status") or "unread").strip().lower()
        if read_status not in _VALID_READ_STATUS:
            read_status = "unread"

        year = CollectionService._safe_int_or_none(payload.get("year"))
        citation_count = CollectionService._safe_int(payload.get("citation_count"))
        impact_factor = CollectionService._safe_nonnegative_float_or_none(payload.get("impact_factor"))
        fields_of_study = CollectionService._normalize_text_list(
            payload.get("fields_of_study"),
            max_size=8,
        )

        return SavedPaperItem(
            saved_paper_id=str(row.get("id") or ""),
            paper_id=str(row.get("paper_id") or ""),
            read_status=read_status,
            saved_at=row.get("saved_at"),
            last_opened_at=row.get("last_opened_at"),
            collection_ids=[
                str(item)
                for item in (row.get("collection_ids") or [])
                if str(item).strip()
            ],
            metadata=SavedPaperMetadata(
                title=str(payload.get("title") or ""),
                abstract=str(payload.get("abstract") or ""),
                authors=authors,
                year=year,
                publication_date=str(payload.get("publication_date") or ""),
                citation_count=citation_count,
                impact_factor=impact_factor,
                fields_of_study=fields_of_study,
                venue=str(payload.get("venue") or ""),
                url=str(payload.get("url") or "") or None,
            ),
        )

    @staticmethod
    def _to_saved_paper_note_item(row: dict[str, Any]) -> SavedPaperNoteItem:
        return SavedPaperNoteItem(
            note_id=str(row.get("id") or "").strip(),
            saved_paper_id=str(row.get("saved_paper_id") or "").strip(),
            content=str(row.get("content") or "").strip(),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@lru_cache
def get_collection_service() -> CollectionService:
    return CollectionService()
