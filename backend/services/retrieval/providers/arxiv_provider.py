from __future__ import annotations

from datetime import datetime
import re
from typing import Any
import xml.etree.ElementTree as ET

import httpx

from core.settings import get_settings
from services.retrieval.providers.base import RetrievalProvider


class ArxivProvider(RetrievalProvider):
    name = "arxiv"
    API_URL = "https://export.arxiv.org/api/query"
    _NS = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(self) -> None:
        settings = get_settings()
        self.timeout = settings.http_timeout_seconds

    def search_papers(self, query: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        safe_query = str(query or "").strip()
        if not safe_query:
            return []
        safe_limit = max(1, min(int(limit), 50))
        payload = self._query_api(
            params={
                "search_query": f"all:{safe_query}",
                "start": max(0, int(offset)),
                "max_results": safe_limit,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        return self._parse_feed(payload)

    def supports_seed_input(self, input_type: str) -> bool:
        return str(input_type or "").strip().lower() == "arxiv_id"

    def fetch_seed_paper(
        self,
        *,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        normalized_type = str(input_type or "").strip().lower()
        if normalized_type != "arxiv_id":
            return None

        paper_id = self._normalize_arxiv_id(input_value)
        if not paper_id:
            return None

        payload = self._query_api(
            params={
                "id_list": paper_id,
                "max_results": 1,
            }
        )
        papers = self._parse_feed(payload)
        return papers[0] if papers else None

    def _query_api(self, *, params: dict[str, Any]) -> str:
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(self.API_URL, params=params)
            response.raise_for_status()
            return response.text

    def _parse_feed(self, payload: str) -> list[dict[str, Any]]:
        root = ET.fromstring(payload)
        papers: list[dict[str, Any]] = []
        for entry in root.findall("atom:entry", self._NS):
            paper = self._parse_entry(entry)
            if paper:
                papers.append(paper)
        return papers

    def _parse_entry(self, entry: ET.Element) -> dict[str, Any] | None:
        entry_id = self._entry_text(entry, "atom:id")
        title = self._clean_text(self._entry_text(entry, "atom:title"))
        if not title:
            return None

        arxiv_id = self._extract_arxiv_id(entry_id)
        if not arxiv_id:
            arxiv_id = self._slug_title(title)

        summary = self._clean_text(self._entry_text(entry, "atom:summary"))
        published = self._entry_text(entry, "atom:published")
        year, month = self._extract_year_month(published)
        authors = [
            self._clean_text(item.findtext("atom:name", default="", namespaces=self._NS))
            for item in entry.findall("atom:author", self._NS)
        ]
        authors = [item for item in authors if item]

        fields = [
            str(item.get("term") or "").strip()
            for item in entry.findall("atom:category", self._NS)
            if str(item.get("term") or "").strip()
        ]

        return {
            "paper_id": f"arxiv:{arxiv_id}",
            "title": title,
            "abstract": summary,
            "year": year,
            "month": month,
            "publication_date": published,
            "citation_count": 0,
            "venue": "arXiv",
            "fields_of_study": list(dict.fromkeys(fields[:6])),
            "authors": authors[:8],
            "url": self._build_abs_url(arxiv_id),
        }

    def _entry_text(self, entry: ET.Element, path: str) -> str:
        return str(entry.findtext(path, default="", namespaces=self._NS) or "").strip()

    @staticmethod
    def _clean_text(raw_text: str) -> str:
        return re.sub(r"\s+", " ", str(raw_text or "").strip())

    @classmethod
    def _normalize_arxiv_id(cls, raw_value: str) -> str:
        value = str(raw_value or "").strip()
        value = re.sub(r"^arxiv:\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(
            r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"\.pdf$", "", value, flags=re.IGNORECASE).strip().strip("/")
        return value

    @classmethod
    def _extract_arxiv_id(cls, raw_text: str) -> str:
        value = cls._normalize_arxiv_id(raw_text)
        if not value:
            return ""
        value = value.split("?")[0].split("#")[0].strip()
        match = re.search(
            r"(?:(?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[a-z\-]+)?/\d{7}))(?:v\d+)?",
            value,
            flags=re.IGNORECASE,
        )
        if not match:
            return value
        return re.sub(r"v\d+$", "", match.group(0), flags=re.IGNORECASE)

    @staticmethod
    def _extract_year_month(publication_date: str) -> tuple[int | None, int | None]:
        safe_date = str(publication_date or "").strip()
        if not safe_date:
            return None, None
        try:
            parsed = datetime.fromisoformat(safe_date.replace("Z", "+00:00"))
            return int(parsed.year), int(parsed.month)
        except ValueError:
            return None, None

    @staticmethod
    def _build_abs_url(arxiv_id: str) -> str:
        safe_id = str(arxiv_id or "").strip()
        if not safe_id:
            return ""
        return f"https://arxiv.org/abs/{safe_id}"

    @staticmethod
    def _slug_title(title: str) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")
        return value[:48] or "unknown"
