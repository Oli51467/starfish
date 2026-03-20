from __future__ import annotations

from functools import lru_cache
import logging
from threading import Lock
from typing import Any
from uuid import uuid4

from core.settings import get_settings

try:  # pragma: no cover - import guard for optional environments
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Json
except ImportError:  # pragma: no cover - import guard for optional environments
    psycopg = None
    dict_row = None
    Json = None

logger = logging.getLogger(__name__)


class PaperSignalRepository:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._table_ready = False
        self._table_lock = Lock()

    def create_event(
        self,
        *,
        user_id: str,
        saved_paper_id: str,
        paper_id: str,
        event_type: str,
        title: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        self._ensure_table()
        safe_user_id = str(user_id or "").strip()
        safe_saved_paper_id = str(saved_paper_id or "").strip()
        safe_paper_id = str(paper_id or "").strip()
        safe_event_type = str(event_type or "").strip().lower()
        safe_title = str(title or "").strip()
        safe_content = str(content or "").strip()
        if not safe_user_id or not safe_saved_paper_id or not safe_paper_id:
            return None
        if not safe_event_type or not safe_title or not safe_content:
            return None

        event_id = f"signal-event-{uuid4().hex[:16]}"
        safe_payload = payload if isinstance(payload, dict) else {}

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO saved_paper_signal_events (
                    id,
                    user_id,
                    saved_paper_id,
                    paper_id,
                    event_type,
                    title,
                    content,
                    payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id,
                          saved_paper_id,
                          paper_id,
                          event_type,
                          title,
                          content,
                          payload,
                          is_read,
                          created_at
                """,
                (
                    event_id,
                    safe_user_id,
                    safe_saved_paper_id,
                    safe_paper_id,
                    safe_event_type,
                    safe_title,
                    safe_content,
                    Json(safe_payload),
                ),
            )
            return cursor.fetchone()

    def list_events(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
        unread_only: bool,
        paper_id: str = "",
        saved_paper_id: str = "",
    ) -> tuple[list[dict[str, Any]], int, int]:
        self._ensure_table()
        safe_user_id = str(user_id or "").strip()
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(50, int(page_size)))
        offset = (safe_page - 1) * safe_page_size
        safe_paper_id = str(paper_id or "").strip()
        safe_saved_paper_id = str(saved_paper_id or "").strip()
        if not safe_user_id:
            return [], 0, 0

        where_conditions = ["user_id = %s"]
        where_params: list[Any] = [safe_user_id]
        if safe_paper_id:
            where_conditions.append("paper_id = %s")
            where_params.append(safe_paper_id)
        if safe_saved_paper_id:
            where_conditions.append("saved_paper_id = %s")
            where_params.append(safe_saved_paper_id)
        where_sql = " AND ".join(where_conditions)

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(1) AS total,
                           COUNT(1) FILTER (WHERE is_read = FALSE) AS unread_count
                    FROM saved_paper_signal_events
                    WHERE {where_sql}
                    """,
                    tuple(where_params),
                )
                count_row = cursor.fetchone() or {"total": 0, "unread_count": 0}
                total = int(count_row.get("total") or 0)
                unread_count = int(count_row.get("unread_count") or 0)

                if unread_only:
                    cursor.execute(
                        f"""
                        SELECT id,
                               saved_paper_id,
                               paper_id,
                               event_type,
                               title,
                               content,
                               payload,
                               is_read,
                               created_at
                        FROM saved_paper_signal_events
                        WHERE {where_sql}
                          AND is_read = FALSE
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                        """,
                        (*where_params, safe_page_size, offset),
                    )
                else:
                    cursor.execute(
                        f"""
                        SELECT id,
                               saved_paper_id,
                               paper_id,
                               event_type,
                               title,
                               content,
                               payload,
                               is_read,
                               created_at
                        FROM saved_paper_signal_events
                        WHERE {where_sql}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                        """,
                        (*where_params, safe_page_size, offset),
                    )
                rows = cursor.fetchall() or []

        return rows, total, unread_count

    def mark_event_read(self, *, user_id: str, event_id: str) -> bool:
        self._ensure_table()
        safe_user_id = str(user_id or "").strip()
        safe_event_id = str(event_id or "").strip()
        if not safe_user_id or not safe_event_id:
            return False

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE saved_paper_signal_events
                SET is_read = TRUE
                WHERE user_id = %s
                  AND id = %s
                RETURNING id
                """,
                (safe_user_id, safe_event_id),
            )
            row = cursor.fetchone()
        return bool(row and str(row.get("id") or "").strip())

    def _ensure_table(self) -> None:
        if self._table_ready:
            return

        with self._table_lock:
            if self._table_ready:
                return
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS saved_paper_signal_events (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        saved_paper_id TEXT NOT NULL REFERENCES saved_papers(id) ON DELETE CASCADE,
                        paper_id VARCHAR(200) NOT NULL,
                        event_type VARCHAR(40) NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        content TEXT NOT NULL,
                        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        is_read BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_saved_paper_signal_events_user_time
                    ON saved_paper_signal_events (user_id, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_saved_paper_signal_events_user_unread
                    ON saved_paper_signal_events (user_id, is_read, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_saved_paper_signal_events_user_paper
                    ON saved_paper_signal_events (user_id, paper_id, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_saved_paper_signal_events_user_saved
                    ON saved_paper_signal_events (user_id, saved_paper_id, created_at DESC)
                    """
                )
            self._table_ready = True

    def _connect(self):
        if psycopg is None or Json is None:
            raise RuntimeError("psycopg_not_installed")

        try:
            return psycopg.connect(self.settings.postgres_dsn, autocommit=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed connecting to PostgreSQL for paper signal persistence.")
            raise RuntimeError("postgres_connection_failed") from exc


@lru_cache
def get_paper_signal_repository() -> PaperSignalRepository:
    return PaperSignalRepository()
