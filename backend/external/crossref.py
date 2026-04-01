from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from core.settings import get_settings


class CrossrefClientError(RuntimeError):
    """Raised when Crossref API is unavailable or returns invalid payload."""


class CrossrefClient:
    """Crossref API wrapper for DOI-heavy scholarly metadata."""

    BASE_URL = "https://api.crossref.org"

    def __init__(self) -> None:
        settings = get_settings()
        self.timeout = settings.http_timeout_seconds
        self.mailto = settings.crossref_mailto
        self.retry_max_retries = max(0, int(settings.retrieval_retry_max_retries))
        self.retry_base_delay_seconds = max(0.01, float(settings.retrieval_retry_base_delay_seconds))
        self.retry_jitter_seconds = max(0.0, float(settings.retrieval_retry_jitter_seconds))
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=max(8, int(settings.http_client_max_connections)),
                max_keepalive_connections=max(4, int(settings.http_client_max_keepalive_connections)),
            ),
        )

    def search_papers(self, query: str, limit: int = 12, offset: int = 0) -> dict[str, Any]:
        safe_query = str(query or "").strip()
        if not safe_query:
            return {"total": 0, "offset": max(0, int(offset)), "next": None, "papers": []}

        safe_limit = max(1, min(int(limit), 50))
        safe_offset = max(0, int(offset))
        payload = self._get(
            "/works",
            params={
                "query.bibliographic": safe_query,
                "rows": safe_limit,
                "offset": safe_offset,
                "sort": "score",
            },
        )
        message = payload.get("message") if isinstance(payload, dict) else {}
        items = message.get("items") if isinstance(message, dict) else []
        papers = [self._normalize_work(item) for item in (items or []) if isinstance(item, dict)]

        return {
            "total": self._safe_int((message or {}).get("total-results")),
            "offset": safe_offset,
            "next": safe_offset + safe_limit if len(papers) >= safe_limit else None,
            "papers": papers,
        }

    def fetch_paper_by_doi(
        self,
        doi: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any] | None:
        del reference_limit, citation_limit
        normalized_doi = self._normalize_doi(doi)
        if not normalized_doi:
            return None

        payload = self._get(f"/works/{quote(normalized_doi, safe='')}")
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            return None
        return self._normalize_work(message)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        if self.mailto and "mailto" not in request_params:
            request_params["mailto"] = self.mailto

        attempts = max(1, self.retry_max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._client.get(f"{self.BASE_URL}{path}", params=request_params)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    raise CrossrefClientError(str(exc)) from exc
                self._sleep_before_retry(attempt)
                continue

            if response.status_code == 404:
                return {}
            if response.status_code in {429, 502, 503, 504}:
                if attempt >= attempts - 1:
                    raise CrossrefClientError(self._extract_error_message(response))
                self._sleep_before_retry(attempt)
                continue
            if response.status_code >= 500:
                if attempt >= attempts - 1:
                    raise CrossrefClientError(self._extract_error_message(response))
                self._sleep_before_retry(attempt)
                continue
            if response.status_code >= 400:
                raise CrossrefClientError(self._extract_error_message(response))

            try:
                payload = response.json()
            except ValueError as exc:
                raise CrossrefClientError("invalid_crossref_json_response") from exc

            if not isinstance(payload, dict):
                raise CrossrefClientError("invalid_crossref_payload")
            return payload

        if last_error is not None:
            raise CrossrefClientError(str(last_error)) from last_error
        raise CrossrefClientError("crossref_request_failed")

    def _sleep_before_retry(self, attempt: int) -> None:
        base = self.retry_base_delay_seconds * (2 ** max(0, attempt))
        jitter = random.uniform(0.0, self.retry_jitter_seconds) if self.retry_jitter_seconds > 0 else 0.0
        time.sleep(base + jitter)

    def _normalize_work(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = self._first_text(payload.get("title")) or self._first_text(payload.get("short-title"))
        year, month = self._extract_year_month(payload)
        doi = self._normalize_doi(payload.get("DOI") or "")
        url = str(payload.get("URL") or "").strip() or (f"https://doi.org/{doi}" if doi else "")
        venue = self._first_text(payload.get("container-title")) or "Unknown Venue"
        abstract = self._clean_abstract(str(payload.get("abstract") or ""))
        reference_count = self._safe_int(payload.get("reference-count"))

        return {
            "paper_id": f"doi:{doi}" if doi else "",
            "title": title,
            "abstract": abstract,
            "year": year,
            "month": month,
            "publication_date": self._extract_publication_date(payload),
            "citation_count": self._safe_int(payload.get("is-referenced-by-count")),
            "venue": venue,
            "fields_of_study": self._normalize_subjects(payload.get("subject")),
            "authors": self._extract_authors(payload),
            "url": url or None,
            "reference_count": reference_count,
            "references": [],
            "citations": [],
            "external_ids": {"DOI": doi} if doi else {},
        }

    @staticmethod
    def _first_text(raw_value: Any) -> str:
        if isinstance(raw_value, list):
            for item in raw_value:
                text = str(item or "").strip()
                if text:
                    return text
            return ""
        return str(raw_value or "").strip()

    @classmethod
    def _normalize_doi(cls, raw_value: Any) -> str:
        text = str(raw_value or "").strip()
        if not text:
            return ""
        text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
        text = text.strip()
        return text.lower()

    @classmethod
    def _extract_year_month(cls, payload: dict[str, Any]) -> tuple[int | None, int | None]:
        for key in ("published-print", "published-online", "issued", "created"):
            date_payload = payload.get(key) or {}
            parsed = cls._parse_date_parts(date_payload.get("date-parts"))
            if parsed != (None, None):
                return parsed
        return None, None

    @classmethod
    def _extract_publication_date(cls, payload: dict[str, Any]) -> str:
        for key in ("published-print", "published-online", "issued", "created"):
            date_payload = payload.get(key) or {}
            date_parts = date_payload.get("date-parts")
            parsed = cls._parse_date_parts(date_parts)
            year, month = parsed
            if year is None:
                continue
            if month is None:
                return f"{year:04d}"
            day = cls._parse_day(date_parts)
            if day is None:
                return f"{year:04d}-{month:02d}"
            return f"{year:04d}-{month:02d}-{day:02d}"
        return ""

    @staticmethod
    def _parse_date_parts(raw_value: Any) -> tuple[int | None, int | None]:
        if not isinstance(raw_value, list) or not raw_value:
            return None, None
        head = raw_value[0]
        if not isinstance(head, list) or not head:
            return None, None
        try:
            year = int(head[0])
        except (TypeError, ValueError):
            return None, None
        month: int | None = None
        if len(head) > 1:
            try:
                parsed_month = int(head[1])
                month = parsed_month if 1 <= parsed_month <= 12 else None
            except (TypeError, ValueError):
                month = None
        return year if year > 0 else None, month

    @staticmethod
    def _parse_day(raw_value: Any) -> int | None:
        if not isinstance(raw_value, list) or not raw_value:
            return None
        head = raw_value[0]
        if not isinstance(head, list) or len(head) < 3:
            return None
        try:
            parsed_day = int(head[2])
        except (TypeError, ValueError):
            return None
        return parsed_day if 1 <= parsed_day <= 31 else None

    @staticmethod
    def _normalize_subjects(raw_value: Any) -> list[str]:
        subjects: list[str] = []
        for item in raw_value or []:
            text = str(item or "").strip()
            if not text:
                continue
            subjects.append(text)
            if len(subjects) >= 8:
                break
        return list(dict.fromkeys(subjects))

    @staticmethod
    def _extract_authors(payload: dict[str, Any]) -> list[str]:
        authors: list[str] = []
        for item in payload.get("author") or []:
            if not isinstance(item, dict):
                continue
            given = str(item.get("given") or "").strip()
            family = str(item.get("family") or "").strip()
            full_name = " ".join(part for part in (given, family) if part).strip()
            if full_name:
                authors.append(full_name)
            if len(authors) >= 12:
                break
        return authors

    @staticmethod
    def _clean_abstract(raw_abstract: str) -> str:
        if not raw_abstract:
            return ""
        cleaned = re.sub(r"<[^>]+>", " ", raw_abstract)
        cleaned = cleaned.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _safe_int(raw_value: Any) -> int:
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            return (response.text or "").strip() or f"crossref_api_error_{response.status_code}"

        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            if isinstance(message, dict):
                for key in ("message", "status", "type"):
                    value = message.get(key)
                    if value:
                        return str(value)
        return str(payload)
