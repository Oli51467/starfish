from __future__ import annotations

from external.arxiv_client import ArxivClient
from external.github_client import GitHubClient
from external.semantic_scholar import SemanticScholarClient


class PaperFetcher:
    """Normalize different input types into a single seed-paper document."""

    def __init__(self) -> None:
        self.semantic = SemanticScholarClient()
        self.arxiv = ArxivClient()
        self.github = GitHubClient()

    def fetch_seed_document(self, input_type: str, input_value: str) -> dict:
        input_type = input_type.strip().lower()
        value = input_value.strip()

        if input_type == "arxiv_id":
            paper = self.arxiv.fetch_by_id(value)
        elif input_type == "doi":
            paper = self.semantic.fetch_paper(value)
        elif input_type == "github_url":
            repo = self.github.fetch_repo(value)
            paper = {
                "paper_id": f"github:{repo['name']}",
                "title": f"Repository: {repo['name']}",
                "year": 2025,
                "authors": ["GitHub Contributors"],
                "venue": "GitHub",
                "citation_count": repo.get("stars", 0),
                "abstract": repo.get("description", ""),
            }
        elif input_type == "pdf":
            paper = {
                "paper_id": f"pdf:{abs(hash(value)) % 1000000}",
                "title": "Uploaded PDF Seed Paper",
                "year": 2024,
                "authors": ["Unknown"],
                "venue": "PDF Upload",
                "citation_count": 0,
                "abstract": "PDF parsing is mocked in skeleton stage.",
            }
        else:
            paper = self.semantic.fetch_paper(value)

        return {
            "input_type": input_type,
            "input_value": value,
            "seed_paper": paper,
        }
