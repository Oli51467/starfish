from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from time import perf_counter
from typing import Any
from urllib.parse import quote

import httpx

from core.settings import get_settings

logger = logging.getLogger(__name__)


class SemanticScholarClientError(RuntimeError):
    """Base exception for Semantic Scholar client failures."""


class SemanticScholarNotFoundError(SemanticScholarClientError):
    """Raised when a paper identifier does not exist in Semantic Scholar."""


class SemanticScholarRateLimitError(SemanticScholarClientError):
    """Raised when Semantic Scholar API rate limit is reached."""


class SemanticScholarClient:
    """Semantic Scholar Graph API wrapper."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    _SDK_MAX_SEARCH_LIMIT = 25
    _SDK_MAX_RELATION_LIMIT = 60
    _SDK_TIMEOUT_CAP_SECONDS = 20
    _SDK_SLOW_CALL_SECONDS = 8.0
    _ARXIV_PATTERN = re.compile(
        r"^(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[a-z\-]+)?/\d{7})(?:v\d+)?$",
        re.IGNORECASE,
    )
    _DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
    _PAPER_FIELDS = ",".join(
        [
            "title",
            "year",
            "authors",
            "venue",
            "journal",
            "publicationVenue",
            "citationCount",
            "referenceCount",
            "publicationDate",
            "abstract",
            "url",
            "externalIds",
            "fieldsOfStudy",
            "s2FieldsOfStudy",
        ]
    )
    _RELATION_FIELDS = (
        "paperId,title,year,citationCount,venue,journal,publicationVenue,abstract,authors,publicationDate"
    )
    _SEARCH_FIELDS = ",".join(
        [
            "title",
            "abstract",
            "paperId",
            "year",
            "publicationDate",
            "citationCount",
            "venue",
            "journal",
            "publicationVenue",
            "fieldsOfStudy",
            "s2FieldsOfStudy",
            "authors",
            "url",
        ]
    )
    _SDK_PAPER_FIELDS = [
        "paperId",
        "title",
        "year",
        "authors",
        "venue",
        "journal",
        "publicationVenue",
        "citationCount",
        "referenceCount",
        "publicationDate",
        "abstract",
        "url",
        "externalIds",
        "fieldsOfStudy",
        "s2FieldsOfStudy",
    ]
    _SDK_RELATION_FIELDS = [
        "paperId",
        "title",
        "year",
        "citationCount",
        "venue",
        "journal",
        "publicationVenue",
        "abstract",
        "authors",
        "publicationDate",
    ]
    _SDK_SEARCH_FIELDS = [
        "paperId",
        "title",
        "abstract",
        "year",
        "publicationDate",
        "citationCount",
        "venue",
        "journal",
        "publicationVenue",
        "fieldsOfStudy",
        "s2FieldsOfStudy",
        "authors",
        "url",
    ]

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.semantic_scholar_api_key
        self.timeout = settings.http_timeout_seconds
        self.retry_max_retries = max(0, int(settings.retrieval_retry_max_retries))
        self.retry_base_delay_seconds = max(0.01, float(settings.retrieval_retry_base_delay_seconds))
        self.retry_jitter_seconds = max(0.0, float(settings.retrieval_retry_jitter_seconds))
        self._prefer_sdk = not bool(self.api_key)
        self._sdk_client: Any | None = None
        self._sdk_import_error: Exception | None = None
        self._client = httpx.Client(
            timeout=self.timeout,
            limits=httpx.Limits(
                max_connections=max(8, int(settings.http_client_max_connections)),
                max_keepalive_connections=max(4, int(settings.http_client_max_keepalive_connections)),
            ),
        )

    @property
    def prefers_sdk(self) -> bool:
        return self._prefer_sdk

    def fetch_paper(
        self,
        paper_id: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any]:
        if self._prefer_sdk:
            return self._fetch_paper_with_sdk(
                paper_id,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        normalized_id = self.normalize_paper_id(paper_id)
        payload = self._get(
            f"/paper/{quote(normalized_id, safe='')}",
            params={"fields": self._PAPER_FIELDS},
        )

        references = self.fetch_references(
            payload.get("paperId") or normalized_id,
            limit=reference_limit,
        )
        citations = self.fetch_citations(
            payload.get("paperId") or normalized_id,
            limit=citation_limit,
        )
        return self._normalize_paper(payload, references, citations)

    def fetch_paper_by_arxiv_id(
        self,
        arxiv_id: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any]:
        return self.fetch_paper(
            f"ARXIV:{arxiv_id.strip()}",
            reference_limit=reference_limit,
            citation_limit=citation_limit,
        )

    def fetch_paper_by_doi(
        self,
        doi: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any]:
        return self.fetch_paper(
            f"DOI:{doi.strip()}",
            reference_limit=reference_limit,
            citation_limit=citation_limit,
        )

    def fetch_references(self, paper_id: str, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        if self._prefer_sdk:
            return self._fetch_references_with_sdk(paper_id, limit=limit, offset=offset)
        normalized_id = self.normalize_paper_id(paper_id)
        payload = self._get(
            f"/paper/{quote(normalized_id, safe='')}/references",
            params={
                "fields": self._RELATION_FIELDS,
                "limit": max(1, min(limit, 1000)),
                "offset": max(0, offset),
            },
        )

        return [
            self._normalize_related_paper(item.get("citedPaper") or {})
            for item in payload.get("data", [])
        ]

    def fetch_citations(self, paper_id: str, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        if self._prefer_sdk:
            return self._fetch_citations_with_sdk(paper_id, limit=limit, offset=offset)
        normalized_id = self.normalize_paper_id(paper_id)
        payload = self._get(
            f"/paper/{quote(normalized_id, safe='')}/citations",
            params={
                "fields": self._RELATION_FIELDS,
                "limit": max(1, min(limit, 1000)),
                "offset": max(0, offset),
            },
        )

        return [
            self._normalize_related_paper(item.get("citingPaper") or {})
            for item in payload.get("data", [])
        ]

    def search_papers(self, query: str, limit: int = 12, offset: int = 0) -> dict[str, Any]:
        if self._prefer_sdk:
            return self._search_papers_with_sdk(query, limit=limit, offset=offset)
        payload = self._get(
            "/paper/search",
            params={
                "query": query.strip(),
                "limit": max(1, min(limit, 100)),
                "offset": max(0, offset),
                "fields": self._SEARCH_FIELDS,
            },
        )

        papers = [self._normalize_search_paper(item) for item in payload.get("data", [])]
        return {
            "total": int(payload.get("total") or len(papers)),
            "offset": int(payload.get("offset") or offset),
            "next": payload.get("next"),
            "papers": papers,
        }

    @classmethod
    def normalize_paper_id(cls, paper_id: str) -> str:
        value = paper_id.strip()
        if not value:
            raise ValueError("paper_id must not be empty")

        if ":" in value:
            prefix, suffix = value.split(":", 1)
            normalized_prefix = prefix.upper()
            if normalized_prefix in {"CORPUSID", "DOI", "ARXIV", "MAG", "ACL", "PMID", "PMCID", "URL"}:
                return f"{normalized_prefix}:{suffix}"

        if value.lower().startswith(("http://", "https://")):
            return f"URL:{value}"

        if cls._DOI_PATTERN.match(value):
            return f"DOI:{value}"

        if cls._ARXIV_PATTERN.match(value):
            return f"ARXIV:{value}"

        return value

    @staticmethod
    def _normalize_paper(
        payload: dict[str, Any],
        references: list[dict[str, Any]],
        citations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        authors = [
            author.get("name")
            for author in payload.get("authors", [])
            if isinstance(author, dict) and author.get("name")
        ]
        journal = payload.get("journal") or {}
        publication_venue = payload.get("publicationVenue") or {}
        venue = (
            payload.get("venue")
            or journal.get("name")
            or publication_venue.get("name")
            or "Unknown Venue"
        )
        fields = []
        for field in payload.get("fieldsOfStudy") or []:
            if isinstance(field, str) and field.strip():
                fields.append(field.strip())
        for field in payload.get("s2FieldsOfStudy") or []:
            if isinstance(field, dict) and field.get("category"):
                fields.append(str(field["category"]).strip())
        dedup_fields = list(dict.fromkeys(fields))

        return {
            "paper_id": str(payload.get("paperId") or ""),
            "title": payload.get("title") or "",
            "year": payload.get("year"),
            "month": SemanticScholarClient._extract_month(payload.get("publicationDate")),
            "publication_date": str(payload.get("publicationDate") or ""),
            "authors": authors,
            "venue": venue,
            "citation_count": int(payload.get("citationCount") or 0),
            "reference_count": int(payload.get("referenceCount") or len(references)),
            "abstract": payload.get("abstract") or "",
            "url": payload.get("url"),
            "fields_of_study": dedup_fields,
            "external_ids": payload.get("externalIds") or {},
            "references": references,
            "citations": citations,
        }

    @staticmethod
    def _normalize_related_paper(payload: dict[str, Any]) -> dict[str, Any]:
        journal = payload.get("journal") or {}
        publication_venue = payload.get("publicationVenue") or {}
        venue = (
            payload.get("venue")
            or journal.get("name")
            or publication_venue.get("name")
            or "Unknown Venue"
        )
        authors = [
            author.get("name")
            for author in (payload.get("authors") or [])
            if isinstance(author, dict) and author.get("name")
        ]
        return {
            "paper_id": str(payload.get("paperId") or ""),
            "title": payload.get("title") or "",
            "year": payload.get("year"),
            "publication_date": str(payload.get("publicationDate") or ""),
            "citation_count": int(payload.get("citationCount") or 0),
            "venue": venue,
            "authors": authors,
            "abstract": str(payload.get("abstract") or ""),
        }

    @staticmethod
    def _normalize_search_paper(payload: dict[str, Any]) -> dict[str, Any]:
        journal = payload.get("journal") or {}
        publication_venue = payload.get("publicationVenue") or {}
        venue = (
            payload.get("venue")
            or journal.get("name")
            or publication_venue.get("name")
            or "Unknown Venue"
        )
        fields = []
        for field in payload.get("fieldsOfStudy") or []:
            if isinstance(field, str) and field.strip():
                fields.append(field.strip())
        for field in payload.get("s2FieldsOfStudy") or []:
            if isinstance(field, dict) and field.get("category"):
                fields.append(str(field["category"]).strip())

        dedup_fields = list(dict.fromkeys(fields))
        authors = [
            author.get("name")
            for author in payload.get("authors", [])
            if isinstance(author, dict) and author.get("name")
        ]
        return {
            "paper_id": str(payload.get("paperId") or ""),
            "title": payload.get("title") or "",
            "abstract": payload.get("abstract") or "",
            "year": payload.get("year"),
            "month": SemanticScholarClient._extract_month(payload.get("publicationDate")),
            "publication_date": str(payload.get("publicationDate") or ""),
            "citation_count": int(payload.get("citationCount") or 0),
            "venue": venue,
            "fields_of_study": dedup_fields,
            "authors": authors,
            "url": payload.get("url"),
        }

    def _fetch_paper_with_sdk(
        self,
        paper_id: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any]:
        normalized_id = self.normalize_paper_id(paper_id)
        client = self._get_sdk_client()
        self._ensure_sdk_event_loop()
        try:
            paper_obj = client.get_paper(normalized_id, fields=self._SDK_PAPER_FIELDS)
        except Exception as exc:  # noqa: BLE001
            self._raise_sdk_error(exc)

        payload = self._extract_sdk_raw_dict(paper_obj)
        if not payload:
            raise SemanticScholarClientError("semantic_scholar_sdk_empty_paper_response")

        references = self._fetch_references_with_sdk(
            payload.get("paperId") or normalized_id,
            limit=reference_limit,
            offset=0,
        )
        citations = self._fetch_citations_with_sdk(
            payload.get("paperId") or normalized_id,
            limit=citation_limit,
            offset=0,
        )
        return self._normalize_paper(payload, references, citations)

    def _fetch_references_with_sdk(
        self,
        paper_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        normalized_id = self.normalize_paper_id(paper_id)
        requested_limit = self._safe_positive_int(limit, default=20)
        safe_limit = max(1, min(requested_limit, self._SDK_MAX_RELATION_LIMIT))
        safe_offset = max(0, offset)
        fetch_limit = max(1, min(safe_limit + safe_offset, self._SDK_MAX_RELATION_LIMIT))
        client = self._get_sdk_client()
        self._ensure_sdk_event_loop()
        started_at = perf_counter()
        try:
            results = client.get_paper_references(
                normalized_id,
                fields=self._SDK_RELATION_FIELDS,
                limit=fetch_limit,
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_sdk_error(exc)

        elapsed = perf_counter() - started_at
        raw_items = list(getattr(results, "items", []) or [])
        references: list[dict[str, Any]] = []
        for item in raw_items:
            relation_payload = self._extract_sdk_raw_dict(item)
            paper_payload = self._extract_sdk_raw_dict(relation_payload.get("citedPaper"))
            if not paper_payload:
                paper_payload = self._extract_sdk_raw_dict(getattr(item, "paper", None))
            if not paper_payload:
                continue
            references.append(self._normalize_related_paper(paper_payload))
            if len(references) >= fetch_limit:
                break

        self._log_sdk_call(
            call_name="get_paper_references",
            query_hint=normalized_id,
            requested_limit=requested_limit,
            effective_limit=fetch_limit,
            returned_count=len(references),
            elapsed=elapsed,
        )
        if safe_offset:
            references = references[safe_offset:]
        return references[:safe_limit]

    def _fetch_citations_with_sdk(
        self,
        paper_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        normalized_id = self.normalize_paper_id(paper_id)
        requested_limit = self._safe_positive_int(limit, default=20)
        safe_limit = max(1, min(requested_limit, self._SDK_MAX_RELATION_LIMIT))
        safe_offset = max(0, offset)
        fetch_limit = max(1, min(safe_limit + safe_offset, self._SDK_MAX_RELATION_LIMIT))
        client = self._get_sdk_client()
        self._ensure_sdk_event_loop()
        started_at = perf_counter()
        try:
            results = client.get_paper_citations(
                normalized_id,
                fields=self._SDK_RELATION_FIELDS,
                limit=fetch_limit,
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_sdk_error(exc)

        elapsed = perf_counter() - started_at
        raw_items = list(getattr(results, "items", []) or [])
        citations: list[dict[str, Any]] = []
        for item in raw_items:
            relation_payload = self._extract_sdk_raw_dict(item)
            paper_payload = self._extract_sdk_raw_dict(relation_payload.get("citingPaper"))
            if not paper_payload:
                paper_payload = self._extract_sdk_raw_dict(getattr(item, "paper", None))
            if not paper_payload:
                continue
            citations.append(self._normalize_related_paper(paper_payload))
            if len(citations) >= fetch_limit:
                break

        self._log_sdk_call(
            call_name="get_paper_citations",
            query_hint=normalized_id,
            requested_limit=requested_limit,
            effective_limit=fetch_limit,
            returned_count=len(citations),
            elapsed=elapsed,
        )
        if safe_offset:
            citations = citations[safe_offset:]
        return citations[:safe_limit]

    def _search_papers_with_sdk(self, query: str, *, limit: int, offset: int) -> dict[str, Any]:
        safe_query = str(query or "").strip()
        if not safe_query:
            raise ValueError("query must not be empty")

        requested_limit = self._safe_positive_int(limit, default=12)
        safe_limit = max(1, min(requested_limit, self._SDK_MAX_SEARCH_LIMIT))
        safe_offset = max(0, offset)
        fetch_limit = max(1, min(safe_limit + safe_offset, self._SDK_MAX_SEARCH_LIMIT))
        client = self._get_sdk_client()
        self._ensure_sdk_event_loop()
        started_at = perf_counter()
        try:
            results = client.search_paper(
                safe_query,
                fields=self._SDK_SEARCH_FIELDS,
                limit=fetch_limit,
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_sdk_error(exc)

        elapsed = perf_counter() - started_at
        paper_payloads: list[dict[str, Any]] = []
        total = 0
        next_offset = 0

        if self._extract_sdk_raw_dict(results):
            payload = self._extract_sdk_raw_dict(results)
            if payload:
                paper_payloads = [payload]
                total = 1
                next_offset = 0
        else:
            total = int(getattr(results, "total", 0) or 0)
            next_offset = int(getattr(results, "next", 0) or 0)
            raw_items = list(getattr(results, "items", []) or [])
            for item in raw_items:
                payload = self._extract_sdk_raw_dict(item)
                if payload:
                    paper_payloads.append(payload)
                if len(paper_payloads) >= fetch_limit:
                    break
            if not total:
                total = len(paper_payloads)

        self._log_sdk_call(
            call_name="search_paper",
            query_hint=safe_query,
            requested_limit=requested_limit,
            effective_limit=fetch_limit,
            returned_count=len(paper_payloads),
            elapsed=elapsed,
        )
        selected = paper_payloads[safe_offset : safe_offset + safe_limit]
        papers = [self._normalize_search_paper(item) for item in selected]
        consumed = safe_offset + len(selected)
        if not next_offset and total > consumed:
            next_offset = consumed
        return {
            "total": max(total, consumed),
            "offset": safe_offset,
            "next": next_offset,
            "papers": papers,
        }

    def _get_sdk_client(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        if self._sdk_import_error is not None:
            raise SemanticScholarClientError(
                f"semantic_scholar_sdk_unavailable: {self._sdk_import_error}"
            ) from self._sdk_import_error

        try:
            from semanticscholar import SemanticScholar  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            self._sdk_import_error = exc
            raise SemanticScholarClientError(
                f"semantic_scholar_sdk_unavailable: {exc}"
            ) from exc

        safe_timeout = max(
            3,
            min(self._SDK_TIMEOUT_CAP_SECONDS, int(round(float(self.timeout or 30)))),
        )
        self._sdk_client = SemanticScholar(timeout=safe_timeout, api_key=None, retry=False)
        logger.info(
            "Semantic Scholar SDK initialized (retry=%s, timeout=%ss, search_cap=%s, relation_cap=%s).",
            False,
            safe_timeout,
            self._SDK_MAX_SEARCH_LIMIT,
            self._SDK_MAX_RELATION_LIMIT,
        )
        return self._sdk_client

    @staticmethod
    def _ensure_sdk_event_loop() -> None:
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    @staticmethod
    def _extract_sdk_raw_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        raw_data = getattr(value, "raw_data", None)
        if isinstance(raw_data, dict):
            return raw_data
        return {}

    @staticmethod
    def _safe_positive_int(value: Any, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(1, parsed)

    def _log_sdk_call(
        self,
        *,
        call_name: str,
        query_hint: str,
        requested_limit: int,
        effective_limit: int,
        returned_count: int,
        elapsed: float,
    ) -> None:
        safe_hint = re.sub(r"\s+", " ", str(query_hint or "").strip())[:140]
        if elapsed >= self._SDK_SLOW_CALL_SECONDS:
            logger.warning(
                "Semantic Scholar SDK slow call: method=%s requested=%s effective=%s returned=%s elapsed=%.2fs hint=%s",
                call_name,
                requested_limit,
                effective_limit,
                returned_count,
                elapsed,
                safe_hint,
            )
            return
        logger.debug(
            "Semantic Scholar SDK call: method=%s requested=%s effective=%s returned=%s elapsed=%.2fs hint=%s",
            call_name,
            requested_limit,
            effective_limit,
            returned_count,
            elapsed,
            safe_hint,
        )

    def _raise_sdk_error(self, exc: Exception) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        lowered_message = message.lower()
        exception_name = exc.__class__.__name__
        if exception_name == "ObjectNotFoundException":
            raise SemanticScholarNotFoundError(message) from exc
        if isinstance(exc, ConnectionRefusedError):
            raise SemanticScholarRateLimitError(message) from exc
        if "rate limit" in lowered_message or "too many requests" in lowered_message:
            raise SemanticScholarRateLimitError(message) from exc
        if exception_name in {"InternalServerErrorException", "GatewayTimeoutException", "ServerErrorException"}:
            raise SemanticScholarClientError(message) from exc
        if isinstance(exc, PermissionError):
            logger.warning("Semantic Scholar SDK permission error: %s", message)
            raise SemanticScholarClientError(message) from exc
        raise SemanticScholarClientError(message) from exc

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        attempts = max(1, self.retry_max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._client.get(f"{self.BASE_URL}{path}", params=params, headers=headers)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    raise SemanticScholarClientError(str(exc)) from exc
                self._sleep_before_retry(attempt)
                continue

            status_code = response.status_code
            details = self._extract_error_message(response)
            if status_code == 404:
                raise SemanticScholarNotFoundError(details)
            if status_code == 429 or (status_code == 403 and self._is_rate_limit_message(details)):
                if attempt >= attempts - 1:
                    raise SemanticScholarRateLimitError(details)
                self._sleep_before_retry(attempt)
                continue
            if status_code in {502, 503, 504} or status_code >= 500:
                if attempt >= attempts - 1:
                    raise SemanticScholarClientError(details)
                self._sleep_before_retry(attempt)
                continue
            if status_code >= 400:
                raise SemanticScholarClientError(details)

            try:
                payload = response.json()
            except ValueError as exc:
                raise SemanticScholarClientError("invalid_semantic_scholar_json_response") from exc
            if not isinstance(payload, dict):
                raise SemanticScholarClientError("invalid_semantic_scholar_payload")
            return payload

        if last_error is not None:
            raise SemanticScholarClientError(str(last_error)) from last_error
        raise SemanticScholarClientError("semantic_scholar_request_failed")

    def _sleep_before_retry(self, attempt: int) -> None:
        base = self.retry_base_delay_seconds * (2 ** max(0, attempt))
        jitter = random.uniform(0.0, self.retry_jitter_seconds) if self.retry_jitter_seconds > 0 else 0.0
        time.sleep(base + jitter)

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            return (response.text or "").strip() or f"semantic scholar api error {response.status_code}"

        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                if payload.get(key):
                    return str(payload[key])
        return str(payload)

    @staticmethod
    def _extract_month(publication_date: Any) -> int:
        text = str(publication_date or "").strip()
        if not text:
            return 0
        parts = text.split("-")
        if len(parts) < 2:
            return 0
        try:
            month = int(parts[1])
        except (TypeError, ValueError):
            return 0
        return month if 1 <= month <= 12 else 0

    @staticmethod
    def _is_rate_limit_message(message: str) -> bool:
        lowered = (message or "").lower()
        return "rate limit" in lowered or "too many requests" in lowered
