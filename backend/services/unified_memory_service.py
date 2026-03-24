from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import json
import sqlite3
from typing import Any

from core.settings import get_settings


class UnifiedMemoryService:
    """Shared strategy memory that links runtime sessions, history and graph artifacts."""

    def __init__(self, *, db_path: str | None = None) -> None:
        settings = get_settings()
        configured_path = str(db_path or (getattr(settings, "unified_memory_db_path", "") or "")).strip()
        if configured_path:
            self.db_path = Path(configured_path).expanduser().resolve()
        else:
            self.db_path = Path(__file__).resolve().parents[1] / "cache" / "unified_memory.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS unified_memory_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    mkey TEXT NOT NULL,
                    mvalue TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_unified_memory_user_scope_task_time
                ON unified_memory_entries(user_id, scope, task_kind, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_unified_memory_user_session_time
                ON unified_memory_entries(user_id, session_id, created_at DESC)
                """
            )

    def write_entry(
        self,
        *,
        user_id: str,
        session_id: str,
        scope: str,
        task_kind: str,
        key: str,
        value: str | dict[str, Any],
        tags: dict[str, Any] | None = None,
    ) -> None:
        safe_user_id = str(user_id or "").strip()
        safe_session_id = str(session_id or "").strip()
        safe_scope = str(scope or "").strip().lower()
        safe_task_kind = str(task_kind or "").strip().lower() or "session"
        safe_key = str(key or "").strip()
        if not safe_user_id or not safe_session_id or not safe_scope or not safe_key:
            return

        if isinstance(value, dict):
            try:
                safe_value = json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                safe_value = str(value)
        else:
            safe_value = str(value or "").strip()
        if not safe_value:
            return

        try:
            safe_tags = json.dumps(tags or {}, ensure_ascii=False)
        except (TypeError, ValueError):
            safe_tags = "{}"

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO unified_memory_entries(
                    user_id,
                    session_id,
                    scope,
                    task_kind,
                    mkey,
                    mvalue,
                    tags,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_user_id,
                    safe_session_id,
                    safe_scope,
                    safe_task_kind,
                    safe_key,
                    safe_value,
                    safe_tags,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def read_task_strategy_memory(
        self,
        *,
        user_id: str,
        task_kind: str,
        limit: int = 24,
        lookback_days: int = 45,
    ) -> list[dict[str, Any]]:
        safe_user_id = str(user_id or "").strip()
        safe_task_kind = str(task_kind or "").strip().lower()
        safe_limit = max(1, min(200, int(limit)))
        safe_days = max(1, int(lookback_days))
        if not safe_user_id or not safe_task_kind:
            return []

        threshold = (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, mkey, mvalue, tags, created_at
                FROM unified_memory_entries
                WHERE user_id = ?
                  AND scope = 'strategy'
                  AND task_kind = ?
                  AND created_at >= ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_user_id, safe_task_kind, threshold, safe_limit),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            tags = {}
            raw_tags = str(row["tags"] or "{}").strip() or "{}"
            try:
                parsed_tags = json.loads(raw_tags)
                if isinstance(parsed_tags, dict):
                    tags = parsed_tags
            except json.JSONDecodeError:
                tags = {}

            payload_value: Any = str(row["mvalue"] or "").strip()
            if payload_value:
                try:
                    parsed_value = json.loads(payload_value)
                    payload_value = parsed_value
                except json.JSONDecodeError:
                    pass

            results.append(
                {
                    "session_id": str(row["session_id"] or "").strip(),
                    "key": str(row["mkey"] or "").strip(),
                    "value": payload_value,
                    "tags": tags,
                    "created_at": str(row["created_at"] or "").strip(),
                }
            )
        return results

    def summarize_task_strategy_priors(
        self,
        *,
        user_id: str,
        task_kind: str,
        limit: int = 64,
    ) -> dict[str, dict[str, float]]:
        entries = self.read_task_strategy_memory(
            user_id=user_id,
            task_kind=task_kind,
            limit=limit,
        )
        priors: dict[str, dict[str, float]] = {}
        for item in entries:
            value = item.get("value")
            if not isinstance(value, dict):
                continue
            agent_id = str(value.get("agent_id") or "").strip()
            if not agent_id:
                continue
            approved = bool(value.get("approved"))
            elapsed_ms = float(value.get("elapsed_ms") or 0.0)
            realized_cost = float(value.get("realized_cost") or 0.0)

            bucket = priors.setdefault(
                agent_id,
                {
                    "sample_size": 0.0,
                    "success_count": 0.0,
                    "total_elapsed_ms": 0.0,
                    "total_cost": 0.0,
                },
            )
            bucket["sample_size"] += 1.0
            if approved:
                bucket["success_count"] += 1.0
            bucket["total_elapsed_ms"] += max(0.0, elapsed_ms)
            bucket["total_cost"] += max(0.0, realized_cost)

        for agent_id, bucket in list(priors.items()):
            sample_size = max(1.0, float(bucket.get("sample_size") or 0.0))
            success_count = max(0.0, float(bucket.get("success_count") or 0.0))
            total_elapsed_ms = max(0.0, float(bucket.get("total_elapsed_ms") or 0.0))
            total_cost = max(0.0, float(bucket.get("total_cost") or 0.0))
            priors[agent_id] = {
                "sample_size": sample_size,
                "success_rate": max(0.0, min(1.0, success_count / sample_size)),
                "avg_elapsed_ms": total_elapsed_ms / sample_size,
                "avg_realized_cost": total_cost / sample_size,
            }
        return priors


@lru_cache
def get_unified_memory_service() -> UnifiedMemoryService:
    return UnifiedMemoryService()
