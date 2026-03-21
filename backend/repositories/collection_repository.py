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

_SORT_FIELD_SQL = {
    "saved_at": "sp.saved_at",
    "last_opened_at": "sp.last_opened_at",
    "year": "CASE WHEN COALESCE(sp.paper_payload->>'year', '') ~ '^-?[0-9]+$' THEN (sp.paper_payload->>'year')::INTEGER ELSE 0 END",
    "citation_count": "CASE WHEN COALESCE(sp.paper_payload->>'citation_count', '') ~ '^[0-9]+$' THEN (sp.paper_payload->>'citation_count')::INTEGER ELSE 0 END",
}
_SORT_ORDER_SQL = {
    "asc": "ASC",
    "desc": "DESC",
}


class CollectionRepository:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._table_ready = False
        self._table_lock = Lock()

    def create_collection(
        self,
        *,
        user_id: str,
        name: str,
        color: str,
        emoji: str,
    ) -> dict[str, Any]:
        self._ensure_tables()
        collection_id = str(uuid4())

        try:
            with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO collections (id, user_id, name, color, emoji)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, name, color, emoji, created_at, updated_at
                    """,
                    (collection_id, str(user_id).strip(), name, color, emoji),
                )
                row = cursor.fetchone()
        except Exception as exc:  # noqa: BLE001
            if "duplicate key value" in str(exc).lower():
                raise ValueError("collection_name_conflict") from exc
            raise
        return row or {}

    def list_collections(self, *, user_id: str) -> list[dict[str, Any]]:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT c.id,
                       c.name,
                       c.color,
                       c.emoji,
                       c.created_at,
                       c.updated_at,
                       COUNT(sp.id) AS paper_count,
                       COUNT(
                         CASE
                           WHEN COALESCE(sp.paper_payload->>'save_source', 'manual') = 'manual' THEN 1
                           ELSE NULL
                         END
                       ) AS manual_paper_count,
                       COUNT(
                         CASE
                           WHEN COALESCE(sp.paper_payload->>'save_source', 'manual') = 'auto_research' THEN 1
                           ELSE NULL
                         END
                       ) AS auto_paper_count
                FROM collections AS c
                LEFT JOIN collection_papers AS cp
                  ON cp.collection_id = c.id
                LEFT JOIN saved_papers AS sp
                  ON sp.id = cp.saved_paper_id
                 AND sp.user_id = c.user_id
                WHERE c.user_id = %s
                GROUP BY c.id, c.name, c.color, c.emoji, c.created_at, c.updated_at
                ORDER BY c.created_at DESC
                """,
                (str(user_id).strip(),),
            )
            rows = cursor.fetchall() or []
        return rows

    def get_collection(self, *, user_id: str, collection_id: str) -> dict[str, Any] | None:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT c.id,
                       c.name,
                       c.color,
                       c.emoji,
                       c.created_at,
                       c.updated_at,
                       COUNT(sp.id) AS paper_count
                FROM collections AS c
                LEFT JOIN collection_papers AS cp
                  ON cp.collection_id = c.id
                LEFT JOIN saved_papers AS sp
                  ON sp.id = cp.saved_paper_id
                 AND sp.user_id = c.user_id
                WHERE c.user_id = %s
                  AND c.id = %s
                GROUP BY c.id, c.name, c.color, c.emoji, c.created_at, c.updated_at
                LIMIT 1
                """,
                (str(user_id).strip(), str(collection_id).strip()),
            )
            row = cursor.fetchone()
        return row

    def update_collection(
        self,
        *,
        user_id: str,
        collection_id: str,
        name: str | None = None,
        color: str | None = None,
        emoji: str | None = None,
    ) -> dict[str, Any] | None:
        self._ensure_tables()
        updates: list[str] = []
        params: list[Any] = []
        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if color is not None:
            updates.append("color = %s")
            params.append(color)
        if emoji is not None:
            updates.append("emoji = %s")
            params.append(emoji)

        if updates:
            updates.append("updated_at = NOW()")
            query = f"""
                UPDATE collections
                SET {", ".join(updates)}
                WHERE user_id = %s
                  AND id = %s
                RETURNING id, name, color, emoji, created_at, updated_at
            """
            try:
                with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        query,
                        (*params, str(user_id).strip(), str(collection_id).strip()),
                    )
                    updated = cursor.fetchone()
            except Exception as exc:  # noqa: BLE001
                if "duplicate key value" in str(exc).lower():
                    raise ValueError("collection_name_conflict") from exc
                raise
            if not updated:
                return None

        return self.get_collection(user_id=user_id, collection_id=collection_id)

    def delete_collection(self, *, user_id: str, collection_id: str) -> bool:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                DELETE FROM collections
                WHERE user_id = %s AND id = %s
                RETURNING id
                """,
                (str(user_id).strip(), str(collection_id).strip()),
            )
            deleted = cursor.fetchone()
        return bool(deleted and str(deleted.get("id") or "").strip())

    def cleanup_auto_generated_content(self, *, user_id: str) -> dict[str, int]:
        self._ensure_tables()
        safe_user_id = str(user_id or "").strip()
        if not safe_user_id:
            return {
                "deleted_collections": 0,
                "deleted_papers": 0,
                "deleted_notes": 0,
            }

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH auto_collections AS (
                    SELECT c.id
                    FROM collections AS c
                    WHERE c.user_id = %s
                      AND (
                        c.name LIKE '围绕%%'
                        OR c.name LIKE '探索%%'
                        OR c.name LIKE '%%领域研究%%'
                      )
                ),
                auto_source_papers AS (
                    SELECT sp.id
                    FROM saved_papers AS sp
                    WHERE sp.user_id = %s
                      AND COALESCE(sp.paper_payload->>'save_source', '') = 'auto_research'
                ),
                legacy_auto_papers AS (
                    SELECT sp.id
                    FROM saved_papers AS sp
                    WHERE sp.user_id = %s
                      AND EXISTS (
                        SELECT 1
                        FROM collection_papers AS cp
                        JOIN auto_collections AS ac
                          ON ac.id = cp.collection_id
                        WHERE cp.saved_paper_id = sp.id
                      )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM collection_papers AS cp
                        JOIN collections AS c
                          ON c.id = cp.collection_id
                        WHERE cp.saved_paper_id = sp.id
                          AND c.user_id = %s
                          AND c.id NOT IN (SELECT id FROM auto_collections)
                      )
                ),
                target_papers AS (
                    SELECT id FROM auto_source_papers
                    UNION
                    SELECT id FROM legacy_auto_papers
                ),
                deleted_notes AS (
                    DELETE FROM notes AS n
                    USING target_papers AS tp
                    WHERE n.saved_paper_id = tp.id
                    RETURNING n.id
                ),
                deleted_auto_links AS (
                    DELETE FROM collection_papers AS cp
                    USING auto_collections AS ac
                    WHERE cp.collection_id = ac.id
                    RETURNING cp.saved_paper_id
                ),
                deleted_auto_collections AS (
                    DELETE FROM collections AS c
                    USING auto_collections AS ac
                    WHERE c.id = ac.id
                    RETURNING c.id
                ),
                deleted_target_links AS (
                    DELETE FROM collection_papers AS cp
                    USING target_papers AS tp
                    WHERE cp.saved_paper_id = tp.id
                    RETURNING cp.saved_paper_id
                ),
                deleted_target_papers AS (
                    DELETE FROM saved_papers AS sp
                    USING target_papers AS tp
                    WHERE sp.id = tp.id
                    RETURNING sp.id
                )
                SELECT
                  COALESCE((SELECT COUNT(1) FROM deleted_auto_collections), 0) AS deleted_collections,
                  COALESCE((SELECT COUNT(1) FROM deleted_target_papers), 0) AS deleted_papers,
                  COALESCE((SELECT COUNT(1) FROM deleted_notes), 0) AS deleted_notes
                """,
                (
                    safe_user_id,
                    safe_user_id,
                    safe_user_id,
                    safe_user_id,
                ),
            )
            row = cursor.fetchone() or {}
        return {
            "deleted_collections": max(0, int(row.get("deleted_collections") or 0)),
            "deleted_papers": max(0, int(row.get("deleted_papers") or 0)),
            "deleted_notes": max(0, int(row.get("deleted_notes") or 0)),
        }

    def collection_exists(self, *, user_id: str, collection_id: str) -> bool:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM collections
                WHERE user_id = %s AND id = %s
                LIMIT 1
                """,
                (str(user_id).strip(), str(collection_id).strip()),
            )
            row = cursor.fetchone()
        return bool(row)

    def create_or_get_saved_paper(
        self,
        *,
        user_id: str,
        paper_id: str,
        paper_payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        self._ensure_tables()
        saved_paper_id = str(uuid4())
        safe_payload = paper_payload if isinstance(paper_payload, dict) else {}

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO saved_papers (id, user_id, paper_id, read_status, paper_payload)
                VALUES (%s, %s, %s, 'unread', %s)
                ON CONFLICT (user_id, paper_id)
                DO UPDATE
                SET paper_payload = CASE
                    WHEN COALESCE(saved_papers.paper_payload, '{}'::jsonb) = '{}'::jsonb
                     AND COALESCE(EXCLUDED.paper_payload, '{}'::jsonb) <> '{}'::jsonb
                    THEN EXCLUDED.paper_payload
                    ELSE saved_papers.paper_payload
                END
                RETURNING id, paper_id, read_status, saved_at, last_opened_at, paper_payload, (xmax = 0) AS inserted
                """,
                (
                    saved_paper_id,
                    str(user_id).strip(),
                    str(paper_id).strip(),
                    Json(safe_payload),
                ),
            )
            row = cursor.fetchone() or {}

        inserted = bool(row.get("inserted"))
        row.pop("inserted", None)
        return row, inserted

    def get_saved_paper(self, *, user_id: str, saved_paper_id: str) -> dict[str, Any] | None:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, paper_id, read_status, saved_at, last_opened_at, paper_payload
                FROM saved_papers
                WHERE user_id = %s AND id = %s
                LIMIT 1
                """,
                (str(user_id).strip(), str(saved_paper_id).strip()),
            )
            row = cursor.fetchone()
        return row

    def saved_paper_exists(self, *, user_id: str, saved_paper_id: str) -> bool:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM saved_papers
                WHERE user_id = %s AND id = %s
                LIMIT 1
                """,
                (str(user_id).strip(), str(saved_paper_id).strip()),
            )
            row = cursor.fetchone()
        return bool(row)

    def delete_saved_paper(self, *, user_id: str, saved_paper_id: str) -> bool:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                DELETE FROM saved_papers
                WHERE user_id = %s AND id = %s
                RETURNING id
                """,
                (str(user_id).strip(), str(saved_paper_id).strip()),
            )
            deleted = cursor.fetchone()
        return bool(deleted and str(deleted.get("id") or "").strip())

    def update_saved_paper_status(
        self,
        *,
        user_id: str,
        saved_paper_id: str,
        read_status: str,
        touch_last_opened: bool,
    ) -> dict[str, Any] | None:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE saved_papers
                SET read_status = %s,
                    last_opened_at = CASE
                        WHEN %s THEN NOW()
                        ELSE last_opened_at
                    END
                WHERE user_id = %s
                  AND id = %s
                RETURNING id, paper_id, read_status, saved_at, last_opened_at, paper_payload
                """,
                (
                    str(read_status).strip(),
                    bool(touch_last_opened),
                    str(user_id).strip(),
                    str(saved_paper_id).strip(),
                ),
            )
            updated = cursor.fetchone()
        return updated

    def update_saved_paper_payload(
        self,
        *,
        user_id: str,
        saved_paper_id: str,
        paper_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        self._ensure_tables()
        safe_payload = paper_payload if isinstance(paper_payload, dict) else {}
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE saved_papers
                SET paper_payload = %s
                WHERE user_id = %s
                  AND id = %s
                RETURNING id, paper_id, read_status, saved_at, last_opened_at, paper_payload
                """,
                (
                    Json(safe_payload),
                    str(user_id).strip(),
                    str(saved_paper_id).strip(),
                ),
            )
            updated = cursor.fetchone()
        return updated

    def list_saved_paper_notes(
        self,
        *,
        user_id: str,
        saved_paper_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        self._ensure_tables()
        safe_limit = max(1, min(100, int(limit)))
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT n.id,
                       n.saved_paper_id,
                       n.content,
                       n.created_at,
                       n.updated_at
                FROM notes AS n
                JOIN saved_papers AS sp
                  ON sp.id = n.saved_paper_id
                 AND sp.user_id = n.user_id
                WHERE n.user_id = %s
                  AND n.saved_paper_id = %s
                ORDER BY n.updated_at DESC, n.created_at DESC
                LIMIT %s
                """,
                (
                    str(user_id).strip(),
                    str(saved_paper_id).strip(),
                    safe_limit,
                ),
            )
            rows = cursor.fetchall() or []
        return rows

    def create_saved_paper_note(
        self,
        *,
        user_id: str,
        saved_paper_id: str,
        content: str,
    ) -> dict[str, Any] | None:
        self._ensure_tables()
        safe_user_id = str(user_id).strip()
        safe_saved_paper_id = str(saved_paper_id).strip()
        safe_content = str(content or "").strip()
        if not safe_user_id or not safe_saved_paper_id or not safe_content:
            return None

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM saved_papers
                WHERE id = %s
                  AND user_id = %s
                LIMIT 1
                """,
                (safe_saved_paper_id, safe_user_id),
            )
            if not cursor.fetchone():
                return None

            note_id = str(uuid4())
            cursor.execute(
                """
                INSERT INTO notes (id, user_id, saved_paper_id, content)
                VALUES (%s, %s, %s, %s)
                RETURNING id, saved_paper_id, content, created_at, updated_at
                """,
                (
                    note_id,
                    safe_user_id,
                    safe_saved_paper_id,
                    safe_content,
                ),
            )
            row = cursor.fetchone()
        return row

    def delete_saved_paper_note(
        self,
        *,
        user_id: str,
        saved_paper_id: str,
        note_id: str,
    ) -> bool:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                DELETE FROM notes
                WHERE user_id = %s
                  AND saved_paper_id = %s
                  AND id = %s
                RETURNING id
                """,
                (
                    str(user_id).strip(),
                    str(saved_paper_id).strip(),
                    str(note_id).strip(),
                ),
            )
            row = cursor.fetchone()
        return bool(row and str(row.get("id") or "").strip())

    def list_saved_papers(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
        collection_id: str | None = None,
        manual_only: bool = False,
        read_status: str | None = None,
        keyword: str | None = None,
        sort_by: str = "saved_at",
        sort_order: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        self._ensure_tables()
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(50, int(page_size)))
        offset = (safe_page - 1) * safe_page_size
        safe_sort_by = str(sort_by or "saved_at").strip().lower()
        safe_sort_order = str(sort_order or "desc").strip().lower()
        order_field = _SORT_FIELD_SQL.get(safe_sort_by, _SORT_FIELD_SQL["saved_at"])
        order_clause = _SORT_ORDER_SQL.get(safe_sort_order, _SORT_ORDER_SQL["desc"])

        conditions = ["sp.user_id = %s"]
        params: list[Any] = [str(user_id).strip()]

        if manual_only:
            conditions.append("COALESCE(sp.paper_payload->>'save_source', 'manual') = 'manual'")

        safe_collection_id = str(collection_id or "").strip()
        if safe_collection_id:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM collection_papers AS cp
                    WHERE cp.saved_paper_id = sp.id
                      AND cp.collection_id = %s
                )
                """
            )
            params.append(safe_collection_id)

        safe_read_status = str(read_status or "").strip()
        if safe_read_status:
            conditions.append("sp.read_status = %s")
            params.append(safe_read_status)

        safe_keyword = str(keyword or "").strip()
        if safe_keyword:
            like_keyword = f"%{safe_keyword}%"
            conditions.append(
                """
                (
                    sp.paper_id ILIKE %s
                    OR COALESCE(sp.paper_payload->>'title', '') ILIKE %s
                )
                """
            )
            params.extend([like_keyword, like_keyword])

        where_sql = " AND ".join(conditions)

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(1) AS total
                    FROM saved_papers AS sp
                    WHERE {where_sql}
                    """,
                    tuple(params),
                )
                count_row = cursor.fetchone() or {"total": 0}
                total = int(count_row.get("total") or 0)

                cursor.execute(
                    f"""
                    SELECT sp.id,
                           sp.paper_id,
                           sp.read_status,
                           sp.saved_at,
                           sp.last_opened_at,
                           sp.paper_payload
                    FROM saved_papers AS sp
                    WHERE {where_sql}
                    ORDER BY {order_field} {order_clause}, sp.saved_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, safe_page_size, offset),
                )
                rows = cursor.fetchall() or []

        saved_paper_ids = [str(item.get("id") or "").strip() for item in rows if str(item.get("id") or "").strip()]
        collection_map = self.list_collection_ids_for_saved_papers(saved_paper_ids=saved_paper_ids)
        for row in rows:
            row_id = str(row.get("id") or "").strip()
            row["collection_ids"] = collection_map.get(row_id, [])
        return rows, total

    def attach_saved_paper_to_collection(
        self,
        *,
        user_id: str,
        collection_id: str,
        saved_paper_id: str,
    ) -> bool:
        self._ensure_tables()
        safe_user_id = str(user_id).strip()
        safe_collection_id = str(collection_id).strip()
        safe_saved_paper_id = str(saved_paper_id).strip()
        if not safe_user_id or not safe_collection_id or not safe_saved_paper_id:
            return False

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM collections
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (safe_collection_id, safe_user_id),
            )
            if not cursor.fetchone():
                return False

            cursor.execute(
                """
                SELECT 1
                FROM saved_papers
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (safe_saved_paper_id, safe_user_id),
            )
            if not cursor.fetchone():
                return False

            cursor.execute(
                """
                INSERT INTO collection_papers (collection_id, saved_paper_id)
                VALUES (%s, %s)
                ON CONFLICT (collection_id, saved_paper_id) DO NOTHING
                """,
                (safe_collection_id, safe_saved_paper_id),
            )
        return True

    def detach_saved_paper_from_collection(
        self,
        *,
        user_id: str,
        collection_id: str,
        saved_paper_id: str,
    ) -> bool:
        self._ensure_tables()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                DELETE FROM collection_papers AS cp
                USING collections AS c
                WHERE cp.collection_id = c.id
                  AND c.user_id = %s
                  AND cp.collection_id = %s
                  AND cp.saved_paper_id = %s
                RETURNING cp.saved_paper_id
                """,
                (
                    str(user_id).strip(),
                    str(collection_id).strip(),
                    str(saved_paper_id).strip(),
                ),
            )
            row = cursor.fetchone()
        return bool(row and str(row.get("saved_paper_id") or "").strip())

    def list_collection_ids_for_saved_papers(self, *, saved_paper_ids: list[str]) -> dict[str, list[str]]:
        self._ensure_tables()
        safe_saved_paper_ids = [str(item or "").strip() for item in saved_paper_ids if str(item or "").strip()]
        if not safe_saved_paper_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(safe_saved_paper_ids))
        query = f"""
            SELECT saved_paper_id, collection_id
            FROM collection_papers
            WHERE saved_paper_id IN ({placeholders})
        """
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, tuple(safe_saved_paper_ids))
            rows = cursor.fetchall() or []

        mapped: dict[str, list[str]] = {paper_id: [] for paper_id in safe_saved_paper_ids}
        for row in rows:
            paper_id = str(row.get("saved_paper_id") or "").strip()
            collection_id = str(row.get("collection_id") or "").strip()
            if not paper_id or not collection_id:
                continue
            mapped.setdefault(paper_id, [])
            mapped[paper_id].append(collection_id)
        return mapped

    def _ensure_tables(self) -> None:
        if self._table_ready:
            return

        with self._table_lock:
            if self._table_ready:
                return
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collections (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        color VARCHAR(20) NOT NULL DEFAULT '',
                        emoji VARCHAR(10) NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (user_id, name)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS saved_papers (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        paper_id VARCHAR(200) NOT NULL,
                        read_status VARCHAR(20) NOT NULL DEFAULT 'unread',
                        saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_opened_at TIMESTAMPTZ,
                        paper_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        UNIQUE (user_id, paper_id),
                        CHECK (read_status IN ('unread', 'reading', 'completed'))
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collection_papers (
                        collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                        saved_paper_id TEXT NOT NULL REFERENCES saved_papers(id) ON DELETE CASCADE,
                        added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (collection_id, saved_paper_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tags (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        name VARCHAR(50) NOT NULL,
                        color VARCHAR(20) NOT NULL DEFAULT '',
                        source VARCHAR(20) NOT NULL DEFAULT 'manual',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (user_id, name),
                        CHECK (source IN ('manual', 'auto_concept', 'auto_graph'))
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_tags (
                        saved_paper_id TEXT NOT NULL REFERENCES saved_papers(id) ON DELETE CASCADE,
                        tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                        user_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (saved_paper_id, tag_id, user_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notes (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        saved_paper_id TEXT REFERENCES saved_papers(id) ON DELETE CASCADE,
                        collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
                        content TEXT NOT NULL,
                        mentions JSONB NOT NULL DEFAULT '[]'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CHECK (saved_paper_id IS NOT NULL OR collection_id IS NOT NULL)
                    )
                    """
                )

                # Migration-safe columns for older table shapes.
                cursor.execute(
                    """
                    ALTER TABLE saved_papers
                    ADD COLUMN IF NOT EXISTS paper_payload JSONB NOT NULL DEFAULT '{}'::jsonb
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE collections
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    """
                )

                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_saved_papers_user_saved_at
                    ON saved_papers (user_id, saved_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_collection_papers_collection_added
                    ON collection_papers (collection_id, added_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notes_user_updated_at
                    ON notes (user_id, updated_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_tags_user_tag
                    ON paper_tags (user_id, tag_id)
                    """
                )

            self._table_ready = True

    def _connect(self):
        if psycopg is None or Json is None or dict_row is None:
            raise RuntimeError("psycopg_not_installed")

        try:
            return psycopg.connect(self.settings.postgres_dsn, autocommit=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed connecting to PostgreSQL for collection persistence.")
            raise RuntimeError("postgres_connection_failed") from exc


@lru_cache
def get_collection_repository() -> CollectionRepository:
    return CollectionRepository()
