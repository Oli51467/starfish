from __future__ import annotations

from functools import lru_cache

from core.exceptions import MapNotFoundError
from core.gap_detector import GapDetector
from models.schemas import GapsResponse
from repositories.map_repository import MapRepository, get_map_repository


class GapService:
    def __init__(
        self,
        detector: GapDetector | None = None,
        map_repository: MapRepository | None = None,
    ) -> None:
        self.detector = detector or GapDetector()
        self.map_repository = map_repository or get_map_repository()

    def get_gaps(self, map_id: str, gap_types: list[str] | None, min_score: int) -> GapsResponse:
        if not self.map_repository.has_map(map_id):
            raise MapNotFoundError(f"map_id not found: {map_id}")
        return self.detector.detect(map_id=map_id, gap_types=gap_types, min_score=min_score)


@lru_cache
def get_gap_service() -> GapService:
    return GapService()
