from __future__ import annotations

from functools import lru_cache

from core.lineage_builder import build_lineage
from models.schemas import LineageResponse


class LineageService:
    async def get_lineage(
        self,
        paper_id: str,
        *,
        ancestor_depth: int,
        descendant_depth: int,
        citation_types: list[str] | None,
        force_refresh: bool,
    ) -> LineageResponse:
        return await build_lineage(
            paper_id,
            ancestor_depth=ancestor_depth,
            descendant_depth=descendant_depth,
            citation_types=citation_types,
            force_refresh=force_refresh,
        )


@lru_cache
def get_lineage_service() -> LineageService:
    return LineageService()
