from __future__ import annotations

from functools import lru_cache

from core.exceptions import MapNotFoundError
from core.importance_ranker import ImportanceRanker
from models.schemas import ReadingListResponse
from repositories.map_repository import MapRepository, get_map_repository


class ReadingListService:
    def __init__(
        self,
        ranker: ImportanceRanker | None = None,
        map_repository: MapRepository | None = None,
    ) -> None:
        self.ranker = ranker or ImportanceRanker()
        self.map_repository = map_repository or get_map_repository()

    def get_reading_list(self, map_id: str, focus_area: str | None, max_papers: int) -> ReadingListResponse:
        if not self.map_repository.has_map(map_id):
            raise MapNotFoundError(f"map_id not found: {map_id}")
        safe_max = max(5, min(max_papers, 30))
        return self.ranker.build_reading_list(map_id=map_id, focus_area=focus_area, max_papers=safe_max)


@lru_cache
def get_reading_list_service() -> ReadingListService:
    return ReadingListService()
