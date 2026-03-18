from __future__ import annotations

from typing import Any

from external.semantic_scholar import SemanticScholarClient
from services.retrieval.providers.base import RetrievalProvider


class SemanticScholarProvider(RetrievalProvider):
    name = "semantic_scholar"

    def __init__(self, client: SemanticScholarClient | None = None) -> None:
        self.client = client or SemanticScholarClient()

    def search_papers(self, query: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        payload = self.client.search_papers(query=query, limit=limit, offset=offset)
        return list(payload.get("papers") or [])

    def supports_seed_input(self, input_type: str) -> bool:
        return str(input_type or "").strip().lower() in {"arxiv_id", "doi"}

    def fetch_seed_paper(
        self,
        *,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        normalized_type = str(input_type or "").strip().lower()
        if normalized_type == "arxiv_id":
            return self.client.fetch_paper_by_arxiv_id(
                input_value,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        if normalized_type == "doi":
            return self.client.fetch_paper_by_doi(
                input_value,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        return None
