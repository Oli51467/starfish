from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RetrievalProvider(ABC):
    """Provider interface for multi-source paper retrieval."""

    name: str = ""

    @abstractmethod
    def search_papers(self, query: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        raise NotImplementedError

    def supports_seed_input(self, input_type: str) -> bool:
        return False

    def fetch_seed_paper(
        self,
        *,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any] | None:
        return None
