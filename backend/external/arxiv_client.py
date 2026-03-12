from __future__ import annotations


class ArxivClient:
    """Skeleton arXiv client."""

    def fetch_by_id(self, arxiv_id: str) -> dict:
        return {
            "paper_id": f"arxiv:{arxiv_id}",
            "title": f"arXiv Paper {arxiv_id}",
            "year": 2024,
            "authors": ["Unknown"],
            "venue": "arXiv",
            "citation_count": 0,
            "abstract": "Mock arXiv abstract placeholder.",
        }
