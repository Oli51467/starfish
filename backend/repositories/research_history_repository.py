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


class ResearchHistoryRepository:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._table_ready = False
        self._table_lock = Lock()

    def save_graph_record(
        self,
        *,
        user_id: str,
        user_email: str,
        research_type: str,
        search_record: str,
        search_range: str,
        graph_id: str,
        graph_payload: dict[str, Any],
    ) -> str:
        self._ensure_table()
        history_id = f"history-{uuid4().hex[:12]}"
        safe_research_type = str(research_type or "unknown").strip() or "unknown"
        safe_search_record = str(search_record or "").strip()
        safe_search_range = str(search_range or "").strip()
        safe_graph_id = str(graph_id or "").strip()

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO research_history_records (
                    history_id, user_id, user_email, research_type, search_record, search_range, graph_id, graph_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    history_id,
                    str(user_id).strip(),
                    str(user_email).strip(),
                    safe_research_type,
                    safe_search_record,
                    safe_search_range,
                    safe_graph_id,
                    Json(graph_payload),
                ),
            )
        return history_id

    def list_graph_records(self, *, user_id: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        self._ensure_table()
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(50, int(page_size)))
        offset = (safe_page - 1) * safe_page_size

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT COUNT(1) AS total FROM research_history_records WHERE user_id = %s",
                    (str(user_id).strip(),),
                )
                count_row = cursor.fetchone() or {"total": 0}
                total = int(count_row.get("total") or 0)

                cursor.execute(
                    """
                    SELECT history_id, research_type, search_record, search_range, search_time
                    FROM research_history_records
                    WHERE user_id = %s
                    ORDER BY search_time DESC
                    LIMIT %s OFFSET %s
                    """,
                    (str(user_id).strip(), safe_page_size, offset),
                )
                rows = cursor.fetchall() or []

        items = [
            {
                "history_id": str(row.get("history_id") or ""),
                "research_type": str(row.get("research_type") or "unknown"),
                "search_record": str(row.get("search_record") or ""),
                "search_range": str(row.get("search_range") or ""),
                "search_time": row.get("search_time"),
            }
            for row in rows
            if str(row.get("history_id") or "").strip()
        ]
        return items, total

    def get_graph_record(self, *, user_id: str, history_id: str) -> dict[str, Any] | None:
        self._ensure_table()
        safe_history_id = str(history_id or "").strip()
        if not safe_history_id:
            return None

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT history_id, research_type, search_record, search_range, search_time, graph_payload
                FROM research_history_records
                WHERE user_id = %s AND history_id = %s
                LIMIT 1
                """,
                (str(user_id).strip(), safe_history_id),
            )
            row = cursor.fetchone()

        if not row:
            return None

        payload = row.get("graph_payload")
        if not isinstance(payload, dict):
            return None

        return {
            "history_id": str(row.get("history_id") or ""),
            "research_type": str(row.get("research_type") or "unknown"),
            "search_record": str(row.get("search_record") or ""),
            "search_range": str(row.get("search_range") or ""),
            "search_time": row.get("search_time"),
            "graph_payload": payload,
        }

    def _ensure_table(self) -> None:
        if self._table_ready:
            return

        with self._table_lock:
            if self._table_ready:
                return
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_history_records (
                        history_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        user_email TEXT NOT NULL,
                        research_type TEXT NOT NULL,
                        search_record TEXT NOT NULL,
                        search_range TEXT NOT NULL DEFAULT '',
                        graph_id TEXT NOT NULL,
                        graph_payload JSONB NOT NULL,
                        search_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE research_history_records
                    ADD COLUMN IF NOT EXISTS search_range TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_history_user_time
                    ON research_history_records (user_id, search_time DESC)
                    """
                )
            self._table_ready = True

    def _connect(self):
        if psycopg is None or Json is None:
            raise RuntimeError("psycopg_not_installed")

        try:
            return psycopg.connect(self.settings.postgres_dsn, autocommit=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed connecting to PostgreSQL for research history persistence.")
            raise RuntimeError("postgres_connection_failed") from exc


@lru_cache
def get_research_history_repository() -> ResearchHistoryRepository:
    return ResearchHistoryRepository()
