from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from core.settings import get_settings


class SemanticScholarClientError(RuntimeError):
    """Base exception for Semantic Scholar client failures."""


class SemanticScholarNotFoundError(SemanticScholarClientError):
    """Raised when a paper identifier does not exist in Semantic Scholar."""


class SemanticScholarClient:
    """Semantic Scholar Graph API wrapper."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
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
            "abstract",
            "url",
            "externalIds",
        ]
    )
    _RELATION_FIELDS = "paperId,title,year,citationCount,venue,journal,publicationVenue"
    _SEARCH_FIELDS = ",".join(
        [
            "title",
            "abstract",
            "year",
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

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.semantic_scholar_api_key
        self.timeout = settings.http_timeout_seconds

    def fetch_paper(
        self,
        paper_id: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any]:
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

        return {
            "paper_id": str(payload.get("paperId") or ""),
            "title": payload.get("title") or "",
            "year": payload.get("year"),
            "authors": authors,
            "venue": venue,
            "citation_count": int(payload.get("citationCount") or 0),
            "reference_count": int(payload.get("referenceCount") or len(references)),
            "abstract": payload.get("abstract") or "",
            "url": payload.get("url"),
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
        return {
            "paper_id": str(payload.get("paperId") or ""),
            "title": payload.get("title") or "",
            "year": payload.get("year"),
            "citation_count": int(payload.get("citationCount") or 0),
            "venue": venue,
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
            "citation_count": int(payload.get("citationCount") or 0),
            "venue": venue,
            "fields_of_study": dedup_fields,
            "authors": authors,
            "url": payload.get("url"),
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            with httpx.Client(timeout=self.timeout, headers=headers) as client:
                response = client.get(f"{self.BASE_URL}{path}", params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            details = self._extract_error_message(exc.response)
            if exc.response.status_code == 404:
                raise SemanticScholarNotFoundError(details) from exc
            raise SemanticScholarClientError(details) from exc
        except httpx.RequestError as exc:
            raise SemanticScholarClientError(str(exc)) from exc

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
