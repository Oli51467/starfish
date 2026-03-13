from __future__ import annotations

import re

from external.arxiv_client import ArxivClient
from external.github_client import GitHubClient
from external.openalex import OpenAlexClient, OpenAlexClientError
from external.semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarClientError,
    SemanticScholarNotFoundError,
)


class PaperFetcher:
    """Normalize different input types into a single seed-paper document."""

    _ARXIV_PATTERN = re.compile(
        r"^(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[a-z\-]+)?/\d{7})(?:v\d+)?$",
        re.IGNORECASE,
    )
    _DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

    def __init__(self) -> None:
        self.semantic = SemanticScholarClient()
        self.openalex = OpenAlexClient()
        self.arxiv = ArxivClient()
        self.github = GitHubClient()

    def fetch_seed_document(
        self,
        input_type: str,
        input_value: str,
        reference_limit: int = 20,
        citation_limit: int = 20,
    ) -> dict:
        input_type = input_type.strip().lower()
        value = input_value.strip()

        if input_type == "arxiv_id":
            try:
                paper = self.semantic.fetch_paper_by_arxiv_id(
                    value,
                    reference_limit=reference_limit,
                    citation_limit=citation_limit,
                )
            except (SemanticScholarNotFoundError, SemanticScholarClientError):
                paper = self._fetch_openalex_by_arxiv(
                    value,
                    reference_limit=reference_limit,
                    citation_limit=citation_limit,
                )
        elif input_type == "doi":
            try:
                paper = self.semantic.fetch_paper_by_doi(
                    value,
                    reference_limit=reference_limit,
                    citation_limit=citation_limit,
                )
            except SemanticScholarClientError:
                paper = self._fetch_openalex_by_doi(
                    value,
                    reference_limit=reference_limit,
                    citation_limit=citation_limit,
                )
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
            try:
                paper = self.semantic.fetch_paper(
                    value,
                    reference_limit=reference_limit,
                    citation_limit=citation_limit,
                )
            except SemanticScholarClientError:
                paper = self._fetch_openalex_by_generic_input(
                    value,
                    reference_limit=reference_limit,
                    citation_limit=citation_limit,
                )

        return {
            "input_type": input_type,
            "input_value": value,
            "seed_paper": paper,
        }

    def _fetch_openalex_by_arxiv(
        self,
        arxiv_id: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict:
        try:
            openalex_paper = self.openalex.fetch_paper_by_arxiv_id(
                arxiv_id,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
            if openalex_paper:
                return openalex_paper
        except OpenAlexClientError:
            pass
        return self.arxiv.fetch_by_id(arxiv_id)

    def _fetch_openalex_by_doi(
        self,
        doi: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict:
        try:
            openalex_paper = self.openalex.fetch_paper_by_doi(
                doi,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
            if openalex_paper:
                return openalex_paper
        except OpenAlexClientError:
            pass
        return self._fallback_doi_paper(doi)

    def _fetch_openalex_by_generic_input(
        self,
        value: str,
        *,
        reference_limit: int,
        citation_limit: int,
    ) -> dict:
        normalized = value.strip()
        if self._ARXIV_PATTERN.match(normalized):
            return self._fetch_openalex_by_arxiv(
                normalized,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        if self._DOI_PATTERN.match(normalized):
            return self._fetch_openalex_by_doi(
                normalized,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        return self._fallback_generic_paper(normalized)

    @staticmethod
    def _fallback_doi_paper(doi: str) -> dict:
        return {
            "paper_id": f"doi:{doi}",
            "title": f"DOI Paper {doi}",
            "year": 2024,
            "authors": ["Unknown"],
            "venue": "DOI",
            "citation_count": 0,
            "reference_count": 0,
            "abstract": "Semantic Scholar unavailable, using DOI fallback metadata.",
            "references": [],
            "citations": [],
        }

    @staticmethod
    def _fallback_generic_paper(value: str) -> dict:
        return {
            "paper_id": value,
            "title": f"Paper {value}",
            "year": 2024,
            "authors": ["Unknown"],
            "venue": "Unknown Venue",
            "citation_count": 0,
            "reference_count": 0,
            "abstract": "Semantic Scholar unavailable, using fallback metadata.",
            "references": [],
            "citations": [],
        }
