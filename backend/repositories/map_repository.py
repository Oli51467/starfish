from __future__ import annotations

from functools import lru_cache
from threading import Lock
from typing import Any


class MapRepository:
    """Abstract map payload repository."""

    def save_map(self, map_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_map(self, map_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def has_map(self, map_id: str) -> bool:
        raise NotImplementedError


class InMemoryMapRepository(MapRepository):
    """In-memory map storage for local development and skeleton stage."""

    def __init__(self) -> None:
        self._maps: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def save_map(self, map_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._maps[map_id] = payload

    def get_map(self, map_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._maps.get(map_id)

    def has_map(self, map_id: str) -> bool:
        with self._lock:
            return map_id in self._maps


@lru_cache
def get_map_repository() -> MapRepository:
    return InMemoryMapRepository()
