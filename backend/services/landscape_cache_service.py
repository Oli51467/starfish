from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from functools import lru_cache
from threading import Lock
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from core.settings import get_settings

logger = logging.getLogger(__name__)


class LandscapeCacheService:
    """Public landscape result cache backed by Redis with in-memory fallback."""

    _CACHE_NAMESPACE = "landscape:result:v1"
    _INFLIGHT_NAMESPACE = "landscape:inflight:v1"

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = bool(settings.enable_landscape_cache)
        self.ttl_seconds = max(60, int(settings.landscape_cache_ttl_seconds))
        self.inflight_enabled = bool(settings.enable_landscape_inflight_dedup)
        self.inflight_ttl_seconds = max(60, int(settings.landscape_inflight_ttl_seconds))
        self._memory: dict[str, tuple[float, dict[str, Any]]] = {}
        self._memory_lock = Lock()
        self._inflight_memory: dict[str, tuple[float, str]] = {}
        self._inflight_lock = Lock()

        self._redis: Redis | None = None
        redis_url = str(settings.redis_url or "").strip()
        if redis_url:
            try:
                self._redis = Redis.from_url(redis_url, decode_responses=True)
            except Exception:  # noqa: BLE001
                logger.exception("Failed initializing Redis client for landscape cache.")

    def build_cache_key(
        self,
        *,
        query: str,
        paper_range_years: int | None,
        summary_enabled: bool,
        quick_mode: bool,
    ) -> str:
        normalized_query = re.sub(r"\s+", " ", str(query or "").strip()).lower()
        safe_range = self._normalize_year_range(paper_range_years)
        payload = {
            "query": normalized_query,
            "paper_range_years": safe_range,
            "summary_enabled": bool(summary_enabled),
            "quick_mode": bool(quick_mode),
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return f"{self._CACHE_NAMESPACE}:{digest}"

    async def get(self, cache_key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        memory_hit = self._get_from_memory(cache_key)
        if memory_hit is not None:
            return memory_hit

        redis_hit = await asyncio.to_thread(self._get_from_redis, cache_key)
        if redis_hit is None:
            return None
        self._set_to_memory(cache_key, redis_hit)
        return redis_hit

    async def set(self, cache_key: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        if not cache_key.strip():
            return
        if not isinstance(payload, dict):
            return

        self._set_to_memory(cache_key, payload)
        await asyncio.to_thread(self._set_to_redis, cache_key, payload)

    async def get_inflight_task(self, cache_key: str) -> str | None:
        if not self.inflight_enabled:
            return None
        memory_hit = self._get_inflight_from_memory(cache_key)
        if memory_hit:
            return memory_hit

        redis_hit = await asyncio.to_thread(self._get_inflight_from_redis, cache_key)
        if redis_hit:
            self._set_inflight_to_memory(cache_key, redis_hit)
        return redis_hit

    async def acquire_inflight(self, cache_key: str, task_id: str) -> tuple[bool, str | None]:
        if not self.inflight_enabled:
            return True, None
        safe_task_id = str(task_id or "").strip()
        if not safe_task_id:
            return False, None

        local_acquired, local_existing = self._acquire_inflight_local(cache_key, safe_task_id)
        if not local_acquired:
            return False, local_existing

        redis_acquired, redis_existing = await asyncio.to_thread(
            self._acquire_inflight_redis,
            cache_key,
            safe_task_id,
        )
        if redis_acquired:
            return True, None

        if redis_existing:
            self._set_inflight_to_memory(cache_key, redis_existing)
            return False, redis_existing

        # Redis is unavailable or unknown state; keep local lock to ensure single-process dedup.
        return True, None

    async def release_inflight(self, cache_key: str, *, expected_task_id: str | None = None) -> None:
        if not self.inflight_enabled:
            return
        self._release_inflight_local(cache_key, expected_task_id=expected_task_id)
        await asyncio.to_thread(self._release_inflight_redis, cache_key, expected_task_id)

    def _get_from_memory(self, cache_key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._memory_lock:
            item = self._memory.get(cache_key)
            if item is None:
                return None
            expire_at, payload = item
            if expire_at <= now:
                self._memory.pop(cache_key, None)
                return None
            return payload

    def _set_to_memory(self, cache_key: str, payload: dict[str, Any]) -> None:
        expire_at = time.time() + self.ttl_seconds
        with self._memory_lock:
            self._memory[cache_key] = (expire_at, payload)

    def _get_inflight_from_memory(self, cache_key: str) -> str | None:
        now = time.time()
        with self._inflight_lock:
            item = self._inflight_memory.get(cache_key)
            if item is None:
                return None
            expire_at, task_id = item
            if expire_at <= now:
                self._inflight_memory.pop(cache_key, None)
                return None
            return task_id

    def _set_inflight_to_memory(self, cache_key: str, task_id: str) -> None:
        expire_at = time.time() + self.inflight_ttl_seconds
        with self._inflight_lock:
            self._inflight_memory[cache_key] = (expire_at, task_id)

    def _acquire_inflight_local(self, cache_key: str, task_id: str) -> tuple[bool, str | None]:
        now = time.time()
        with self._inflight_lock:
            current = self._inflight_memory.get(cache_key)
            if current is not None:
                expire_at, current_task_id = current
                if expire_at > now and current_task_id:
                    return False, current_task_id
            self._inflight_memory[cache_key] = (now + self.inflight_ttl_seconds, task_id)
            return True, None

    def _release_inflight_local(self, cache_key: str, *, expected_task_id: str | None = None) -> None:
        expected = str(expected_task_id or "").strip()
        with self._inflight_lock:
            current = self._inflight_memory.get(cache_key)
            if current is None:
                return
            _, current_task_id = current
            if expected and current_task_id != expected:
                return
            self._inflight_memory.pop(cache_key, None)

    def _get_from_redis(self, cache_key: str) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(cache_key)
        except RedisError:
            logger.warning("Redis get failed for cache key: %s", cache_key)
            return None
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Redis cache payload is not valid JSON, key=%s", cache_key)
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _set_to_redis(self, cache_key: str, payload: dict[str, Any]) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(cache_key, json.dumps(payload, ensure_ascii=False), ex=self.ttl_seconds)
        except RedisError:
            logger.warning("Redis set failed for cache key: %s", cache_key)

    def _get_inflight_from_redis(self, cache_key: str) -> str | None:
        if self._redis is None:
            return None
        key = self._inflight_cache_key(cache_key)
        try:
            raw = self._redis.get(key)
        except RedisError:
            logger.warning("Redis get failed for in-flight key: %s", key)
            return None
        value = str(raw or "").strip()
        return value or None

    def _acquire_inflight_redis(self, cache_key: str, task_id: str) -> tuple[bool, str | None]:
        if self._redis is None:
            return True, None
        key = self._inflight_cache_key(cache_key)
        try:
            created = self._redis.set(key, task_id, ex=self.inflight_ttl_seconds, nx=True)
        except RedisError:
            logger.warning("Redis set NX failed for in-flight key: %s", key)
            return False, None
        if created:
            return True, None
        try:
            existing = self._redis.get(key)
        except RedisError:
            logger.warning("Redis get after NX failure failed for in-flight key: %s", key)
            return False, None
        existing_task_id = str(existing or "").strip()
        return False, existing_task_id or None

    def _release_inflight_redis(self, cache_key: str, expected_task_id: str | None) -> None:
        if self._redis is None:
            return
        key = self._inflight_cache_key(cache_key)
        expected = str(expected_task_id or "").strip()
        try:
            if not expected:
                self._redis.delete(key)
                return
            self._redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) "
                "else return 0 end",
                1,
                key,
                expected,
            )
        except RedisError:
            logger.warning("Redis release failed for in-flight key: %s", key)

    def _inflight_cache_key(self, cache_key: str) -> str:
        suffix = str(cache_key or "").rsplit(":", 1)[-1]
        if not suffix:
            suffix = hashlib.sha256(str(cache_key or "").encode("utf-8")).hexdigest()
        return f"{self._INFLIGHT_NAMESPACE}:{suffix}"

    @staticmethod
    def _normalize_year_range(raw_value: int | None) -> int | None:
        if raw_value is None:
            return None
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return min(30, parsed)


@lru_cache
def get_landscape_cache_service() -> LandscapeCacheService:
    return LandscapeCacheService()
