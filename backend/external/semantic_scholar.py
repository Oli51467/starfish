from __future__ import annotations

from typing import Any

import httpx

from core.settings import get_settings


class SemanticScholarClient:
    """Minimal Semantic Scholar API wrapper for stage-1 skeleton."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.semantic_scholar_api_key
        self.timeout = settings.http_timeout_seconds

    def fetch_paper(self, paper_id: str) -> dict[str, Any]:
        # Skeleton mode: return deterministic mock payload.
        return {
            "paper_id": paper_id,
            "title": f"Seed Paper {paper_id}",
            "year": 2024,
            "authors": ["Author A", "Author B"],
            "venue": "MockConf",
            "citation_count": 128,
            "abstract": "This is a mock abstract from Semantic Scholar skeleton client.",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            response = client.get(f"{self.BASE_URL}{path}", params=params)
            response.raise_for_status()
            return response.json()
