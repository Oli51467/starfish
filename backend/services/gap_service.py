from __future__ import annotations

from functools import lru_cache

from core.gap_detector import GapDetector
from core.task_manager import get_task_manager
from models.schemas import GapsResponse


class GapService:
    def __init__(self) -> None:
        self.detector = GapDetector()
        self.task_manager = get_task_manager()

    def get_gaps(self, map_id: str, gap_types: list[str] | None, min_score: int) -> GapsResponse:
        if not self.task_manager.get_map(map_id):
            raise KeyError("map_not_found")
        return self.detector.detect(map_id=map_id, gap_types=gap_types, min_score=min_score)


@lru_cache
def get_gap_service() -> GapService:
    return GapService()
