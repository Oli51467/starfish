from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from core.settings import get_settings


class OpenAlexClientError(RuntimeError):
    """Raised when OpenAlex API is unavailable or returns invalid payload."""


class OpenAlexClient:
    """OpenAlex API wrapper used as Semantic Scholar rate-limit fallback."""

    BASE_URL = "https://api.openalex.org"
    _WORK_SELECT = ",".join(
        [
            "id",
            "title",
            "publication_year",
            "publication_date",
            "cited_by_count",
            "authorships",
            "primary_location",
            "abstract_inverted_index",
            "referenced_works",
            "doi",
        ]
    )
    _SEARCH_SELECT = ",".join(
        [
            "id",
            "title",
            "publication_year",
            "publication_date",
            "cited_by_count",
            "primary_location",
            "abstract_inverted_index",
            "authorships",
            "concepts",
            "doi",
        ]
    )

    def __init__(self) -> None:
        settings = get_settings()
        self.timeout = settings.http_timeout_seconds
        self.mailto = settings.openalex_mailto

    def fetch_paper_by_arxiv_id(
        self,
        arxiv_id: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any] | None:
        normalized_arxiv = arxiv_id.strip()
        payload = self._get(
            f"/works/arXiv:{arxiv_id.strip()}",
            params={"select": self._WORK_SELECT},
        )
        if payload is None:
            return self.fetch_paper_by_doi(
                f"10.48550/arXiv.{normalized_arxiv}",
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        if payload is None:
            return None
        return self._normalize_paper(payload, reference_limit=reference_limit, citation_limit=citation_limit)

    def fetch_paper_by_doi(
        self,
        doi: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any] | None:
        normalized_doi = doi.strip()
        if normalized_doi.lower().startswith("doi:"):
            normalized_doi = normalized_doi.split(":", 1)[1]

        doi_url = f"https://doi.org/{normalized_doi}"
        payload = self._get(
            f"/works/{quote(doi_url, safe='')}",
            params={"select": self._WORK_SELECT},
        )
        if payload is None:
            search_payload = self._get(
                "/works",
                params={
                    "filter": f"doi:{doi_url}",
                    "per-page": 1,
                    "select": self._WORK_SELECT,
                },
            )
            if not search_payload:
                return None
            payload = (search_payload.get("results") or [None])[0]
            if payload is None:
                return None

        return self._normalize_paper(payload, reference_limit=reference_limit, citation_limit=citation_limit)

    def fetch_paper(
        self,
        paper_id: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict[str, Any] | None:
        compact_id = self._normalize_openalex_compact_id(paper_id)
        if not compact_id:
            return None

        full_id = self._to_openalex_full_id(compact_id)
        payload = self._get(
            f"/works/{quote(full_id, safe='')}",
            params={"select": self._WORK_SELECT},
        )
        if payload is None:
            return None

        return self._normalize_paper(payload, reference_limit=reference_limit, citation_limit=citation_limit)

    def search_papers(self, query: str, limit: int = 12, offset: int = 0) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 50))
        safe_offset = max(0, offset)
        page = safe_offset // safe_limit + 1
        payload = self._get(
            "/works",
            params={
                "search": query.strip(),
                "per-page": safe_limit,
                "page": page,
                "select": self._SEARCH_SELECT,
            },
        )
        if not payload:
            return {"total": 0, "offset": safe_offset, "next": None, "papers": []}

        works = payload.get("results") or []
        papers = [self._normalize_search_work(work) for work in works if isinstance(work, dict)]
        meta = payload.get("meta") or {}
        return {
            "total": int(meta.get("count") or len(papers)),
            "offset": safe_offset,
            "next": meta.get("next_cursor"),
            "papers": papers,
        }

    def fetch_references(self, referenced_works: list[str], limit: int = 20) -> list[dict[str, Any]]:
        if not referenced_works:
            return []
        works = self._get_papers_batch(referenced_works[: max(1, min(limit, 50))])
        return [self._normalize_related_work(work) for work in works]

    def fetch_citations(self, openalex_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if not openalex_id:
            return []

        safe_limit = max(1, min(limit, 50))
        payload = self._get(
            "/works",
            params={
                "filter": f"cites:{openalex_id}",
                "per-page": safe_limit,
                "select": self._WORK_SELECT,
                "sort": "cited_by_count:desc",
            },
        )
        if not payload:
            return []
        works = payload.get("results") or []
        return [self._normalize_related_work(work) for work in works if isinstance(work, dict)]

    def fetch_relation_ids(self, paper_id: str, limit: int = 60) -> dict[str, list[str]]:
        """
        Return compact OpenAlex relation ids for one paper.

        Response format:
        {
            "references": ["openalex:W...", ...],
            "citations": ["openalex:W...", ...],
        }
        """
        compact_id = self._normalize_openalex_compact_id(paper_id)
        if not compact_id:
            return {"references": [], "citations": []}

        full_id = self._to_openalex_full_id(compact_id)
        payload = self._get(
            f"/works/{quote(full_id, safe='')}",
            params={"select": "id,referenced_works"},
        )
        if not payload:
            return {"references": [], "citations": []}

        references_raw = payload.get("referenced_works") or []
        references = []
        for item in references_raw[: max(1, min(limit, 200))]:
            related_id = self._compact_openalex_id(item)
            if related_id:
                references.append(f"openalex:{related_id}")

        citations_raw = self.fetch_citations(full_id, limit=max(1, min(limit, 200)))
        citations = []
        for item in citations_raw:
            related = str(item.get("paper_id") or "").strip()
            if related:
                citations.append(related)

        return {
            "references": list(dict.fromkeys(references)),
            "citations": list(dict.fromkeys(citations)),
        }

    def _normalize_paper(
        self,
        payload: dict[str, Any],
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any]:
        openalex_id = self._compact_openalex_id(payload.get("id"))
        references = self.fetch_references(payload.get("referenced_works") or [], limit=reference_limit)
        citations = self.fetch_citations(payload.get("id") or "", limit=citation_limit)

        return {
            "paper_id": f"openalex:{openalex_id}" if openalex_id else "",
            "title": str(payload.get("title") or ""),
            "year": self._safe_int(payload.get("publication_year")),
            "month": self._extract_month(payload.get("publication_date")),
            "publication_date": str(payload.get("publication_date") or ""),
            "authors": self._extract_authors(payload),
            "venue": self._extract_venue(payload),
            "citation_count": self._safe_int(payload.get("cited_by_count")),
            "reference_count": len(payload.get("referenced_works") or []),
            "abstract": self._reconstruct_abstract(payload.get("abstract_inverted_index") or {}),
            "url": self._extract_url(payload),
            "external_ids": self._extract_external_ids(payload, openalex_id),
            "references": references,
            "citations": citations,
        }

    def _normalize_search_work(self, payload: dict[str, Any]) -> dict[str, Any]:
        openalex_id = self._compact_openalex_id(payload.get("id"))
        concepts = payload.get("concepts") or []
        fields: list[str] = []
        for concept in concepts:
            if isinstance(concept, dict) and concept.get("display_name"):
                fields.append(str(concept["display_name"]))

        return {
            "paper_id": f"openalex:{openalex_id}" if openalex_id else "",
            "title": str(payload.get("title") or ""),
            "abstract": self._reconstruct_abstract(payload.get("abstract_inverted_index") or {}),
            "year": self._safe_int(payload.get("publication_year")),
            "month": self._extract_month(payload.get("publication_date")),
            "publication_date": str(payload.get("publication_date") or ""),
            "citation_count": self._safe_int(payload.get("cited_by_count")),
            "venue": self._extract_venue(payload),
            "fields_of_study": list(dict.fromkeys(fields[:5])),
            "authors": self._extract_authors(payload),
            "url": self._extract_url(payload),
        }

    def _normalize_related_work(self, payload: dict[str, Any]) -> dict[str, Any]:
        openalex_id = self._compact_openalex_id(payload.get("id"))
        return {
            "paper_id": f"openalex:{openalex_id}" if openalex_id else "",
            "title": str(payload.get("title") or ""),
            "year": self._safe_int(payload.get("publication_year")),
            "citation_count": self._safe_int(payload.get("cited_by_count")),
            "venue": self._extract_venue(payload),
        }

    def _get_papers_batch(self, openalex_ids: list[str]) -> list[dict[str, Any]]:
        if not openalex_ids:
            return []

        items: list[dict[str, Any]] = []
        for start in range(0, len(openalex_ids), 50):
            chunk = [item for item in openalex_ids[start : start + 50] if item]
            if not chunk:
                continue
            ids_str = "|".join(chunk)
            payload = self._get(
                "/works",
                params={
                    "filter": f"openalex_id:{ids_str}",
                    "per-page": 50,
                    "select": self._WORK_SELECT,
                },
            )
            if not payload:
                continue
            results = payload.get("results") or []
            for result in results:
                if isinstance(result, dict):
                    items.append(result)
        return items

    @classmethod
    def _normalize_openalex_compact_id(cls, paper_id: str) -> str:
        value = str(paper_id or "").strip()
        if not value:
            return ""
        if value.lower().startswith("openalex:"):
            return value.split(":", 1)[1]
        return cls._compact_openalex_id(value)

    @staticmethod
    def _to_openalex_full_id(compact_id: str) -> str:
        value = str(compact_id or "").strip()
        if not value:
            return ""
        if value.lower().startswith("https://openalex.org/"):
            return value
        if value.upper().startswith("W"):
            return f"https://openalex.org/{value}"
        return value

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        request_params = dict(params or {})
        if self.mailto and "mailto" not in request_params:
            request_params["mailto"] = self.mailto

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.BASE_URL}{path}", params=request_params)
        except httpx.RequestError as exc:
            raise OpenAlexClientError(str(exc)) from exc

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise OpenAlexClientError(self._extract_error_message(response))

        try:
            return response.json()
        except ValueError as exc:
            raise OpenAlexClientError("invalid_openalex_json_response") from exc

    @staticmethod
    def _extract_authors(payload: dict[str, Any]) -> list[str]:
        authors: list[str] = []
        for authorship in payload.get("authorships") or []:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author") or {}
            display_name = author.get("display_name")
            if display_name:
                authors.append(str(display_name))
        return authors

    @staticmethod
    def _extract_venue(payload: dict[str, Any]) -> str:
        primary_location = payload.get("primary_location") or {}
        source = primary_location.get("source") or {}
        venue = source.get("display_name")
        return str(venue or "Unknown Venue")

    @staticmethod
    def _extract_url(payload: dict[str, Any]) -> str | None:
        primary_location = payload.get("primary_location") or {}
        return primary_location.get("landing_page_url") or primary_location.get("pdf_url")

    @staticmethod
    def _extract_external_ids(payload: dict[str, Any], openalex_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        if openalex_id:
            result["OpenAlex"] = openalex_id
        doi = str(payload.get("doi") or "").strip()
        if doi:
            result["DOI"] = doi
        return result

    @staticmethod
    def _compact_openalex_id(raw_id: Any) -> str:
        text = str(raw_id or "").strip()
        if not text:
            return ""
        if "/" in text:
            return text.rsplit("/", 1)[-1]
        return text

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

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
    def _reconstruct_abstract(inverted_index: dict[str, list[int]]) -> str:
        if not inverted_index:
            return ""
        words: dict[int, str] = {}
        for word, positions in inverted_index.items():
            if not isinstance(word, str):
                continue
            if not isinstance(positions, list):
                continue
            for pos in positions:
                if isinstance(pos, int):
                    words[pos] = word
        if not words:
            return ""
        return " ".join(words[index] for index in sorted(words.keys()))

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            return (response.text or "").strip() or f"openalex_api_error_{response.status_code}"

        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                if payload.get(key):
                    return str(payload[key])
        return str(payload)
