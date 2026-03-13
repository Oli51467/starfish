from __future__ import annotations

from functools import lru_cache
from threading import Lock
from typing import Any


class LandscapeRepository:
    """Abstract landscape payload repository."""

    def save_landscape(self, landscape_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_landscape(self, landscape_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def has_landscape(self, landscape_id: str) -> bool:
        raise NotImplementedError


class InMemoryLandscapeRepository(LandscapeRepository):
    """In-memory storage for generated domain landscapes."""

    def __init__(self) -> None:
        self._landscapes: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def save_landscape(self, landscape_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._landscapes[landscape_id] = payload

    def get_landscape(self, landscape_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._landscapes.get(landscape_id)

    def has_landscape(self, landscape_id: str) -> bool:
        with self._lock:
            return landscape_id in self._landscapes


@lru_cache
def get_landscape_repository() -> LandscapeRepository:
    return InMemoryLandscapeRepository()
