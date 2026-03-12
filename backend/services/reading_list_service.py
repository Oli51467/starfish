from __future__ import annotations

from functools import lru_cache

from core.importance_ranker import ImportanceRanker
from core.task_manager import get_task_manager
from models.schemas import ReadingListResponse


class ReadingListService:
    def __init__(self) -> None:
        self.ranker = ImportanceRanker()
        self.task_manager = get_task_manager()

    def get_reading_list(self, map_id: str, focus_area: str | None, max_papers: int) -> ReadingListResponse:
        if not self.task_manager.get_map(map_id):
            raise KeyError("map_not_found")
        safe_max = max(5, min(max_papers, 30))
        return self.ranker.build_reading_list(map_id=map_id, focus_area=focus_area, max_papers=safe_max)


@lru_cache
def get_reading_list_service() -> ReadingListService:
    return ReadingListService()
