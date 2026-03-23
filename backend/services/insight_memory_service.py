from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from core.settings import get_settings
from services.insight_agent_contracts import AgentMemoryWriteRecord

_DEFAULT_WORKER_SCOPE = "main"


class InsightMemoryService:
    """Persistent memory service with worker/profile isolation."""

    def __init__(self, *, db_path: str | None = None) -> None:
        settings = get_settings()
        configured_path = str(db_path or settings.insight_memory_db_path or "").strip()
        if configured_path:
            self.db_path = Path(configured_path).expanduser().resolve()
        else:
            self.db_path = Path(__file__).resolve().parents[1] / "cache" / "insight_memory.sqlite3"
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
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    mkey TEXT NOT NULL,
                    mvalue TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_run_scope_key
                ON memory_entries(run_id, scope, mkey, id);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_run_scope_profile_worker_key
                ON memory_entries(run_id, scope, profile_id, worker_id, mkey, id);
                """
            )

    def initialize_run(self, *, run_id: str, history_memory: list[str] | None = None) -> None:
        safe_run_id = str(run_id or "").strip()
        if not safe_run_id:
            return
        safe_history = [str(item).strip() for item in (history_memory or []) if str(item).strip()]
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_entries WHERE run_id = ?", (safe_run_id,))
            for line in safe_history:
                self._insert_entry(
                    conn=conn,
                    run_id=safe_run_id,
                    scope="history_shared",
                    profile_id="",
                    worker_id="",
                    key="history",
                    value=line,
                )

    def _insert_entry(
        self,
        *,
        conn: sqlite3.Connection,
        run_id: str,
        scope: str,
        profile_id: str,
        worker_id: str,
        key: str,
        value: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO memory_entries(run_id, scope, profile_id, worker_id, mkey, mvalue, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                scope,
                profile_id,
                worker_id,
                key,
                value,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    @staticmethod
    def _normalize_worker_id(worker_id: str | None) -> str:
        safe = str(worker_id or "").strip()
        return safe or _DEFAULT_WORKER_SCOPE

    def write(
        self,
        *,
        run_id: str,
        record: AgentMemoryWriteRecord,
        worker_id: str | None = None,
    ) -> None:
        safe_run_id = str(run_id or "").strip()
        if not safe_run_id:
            return
        key = str(record.key or "").strip()
        value = str(record.value or "").strip()
        if not key or not value:
            return
        scope = str(record.scope or "").strip()
        profile_id = str(record.profile_id or "").strip()
        safe_worker_id = self._normalize_worker_id(worker_id)

        insert_profile_id = ""
        insert_worker_id = ""
        if scope == "agent_private":
            if not profile_id:
                return
            insert_profile_id = profile_id
            insert_worker_id = safe_worker_id
        elif scope == "session_shared":
            insert_profile_id = ""
            insert_worker_id = ""
        elif scope == "history_shared":
            insert_profile_id = ""
            insert_worker_id = ""
        else:
            return

        with self._connect() as conn:
            self._insert_entry(
                conn=conn,
                run_id=safe_run_id,
                scope=scope,
                profile_id=insert_profile_id,
                worker_id=insert_worker_id,
                key=key,
                value=value,
            )

    def write_many(
        self,
        *,
        run_id: str,
        records: list[AgentMemoryWriteRecord],
        worker_id: str | None = None,
    ) -> None:
        safe_run_id = str(run_id or "").strip()
        if not safe_run_id:
            return
        safe_worker_id = self._normalize_worker_id(worker_id)
        with self._connect() as conn:
            for item in records or []:
                if not isinstance(item, AgentMemoryWriteRecord):
                    continue
                key = str(item.key or "").strip()
                value = str(item.value or "").strip()
                scope = str(item.scope or "").strip()
                profile_id = str(item.profile_id or "").strip()
                if not key or not value:
                    continue
                if scope == "agent_private":
                    if not profile_id:
                        continue
                    self._insert_entry(
                        conn=conn,
                        run_id=safe_run_id,
                        scope=scope,
                        profile_id=profile_id,
                        worker_id=safe_worker_id,
                        key=key,
                        value=value,
                    )
                elif scope in {"session_shared", "history_shared"}:
                    self._insert_entry(
                        conn=conn,
                        run_id=safe_run_id,
                        scope=scope,
                        profile_id="",
                        worker_id="",
                        key=key,
                        value=value,
                    )

    def _read_rows(
        self,
        *,
        run_id: str,
        scope: str,
        key: str,
        limit: int,
        profile_id: str = "",
        worker_id: str = "",
    ) -> list[str]:
        safe_limit = max(1, int(limit))
        safe_run_id = str(run_id or "").strip()
        safe_key = str(key or "").strip()
        if not safe_run_id or not safe_key:
            return []

        query = """
            SELECT mvalue
            FROM memory_entries
            WHERE run_id = ? AND scope = ? AND mkey = ?
        """
        params: list[Any] = [safe_run_id, scope, safe_key]
        if scope == "agent_private":
            query += " AND profile_id = ? AND worker_id = ?"
            params.extend([profile_id, worker_id])
        query += " ORDER BY id DESC LIMIT ?"
        params.append(safe_limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        values = [str(row["mvalue"] or "") for row in rows if str(row["mvalue"] or "").strip()]
        values.reverse()
        return values

    def read_session(self, *, run_id: str, key: str, limit: int = 8) -> list[str]:
        return self._read_rows(
            run_id=run_id,
            scope="session_shared",
            key=key,
            limit=limit,
        )

    def read_agent(
        self,
        *,
        run_id: str,
        profile_id: str,
        key: str,
        limit: int = 4,
        worker_id: str | None = None,
    ) -> list[str]:
        safe_profile_id = str(profile_id or "").strip()
        if not safe_profile_id:
            return []
        return self._read_rows(
            run_id=run_id,
            scope="agent_private",
            key=key,
            limit=limit,
            profile_id=safe_profile_id,
            worker_id=self._normalize_worker_id(worker_id),
        )

    def read_history(self, *, run_id: str, limit: int = 4) -> list[str]:
        return self._read_rows(
            run_id=run_id,
            scope="history_shared",
            key="history",
            limit=limit,
        )

    def build_session_view(self, *, run_id: str) -> dict[str, list[str]]:
        return {
            "hypotheses": self.read_session(run_id=run_id, key="hypotheses", limit=12),
            "evidence": self.read_session(run_id=run_id, key="evidence", limit=16),
            "decisions": self.read_session(run_id=run_id, key="decisions", limit=16),
            "critic_notes": self.read_session(run_id=run_id, key="critic_notes", limit=12),
        }

    def snapshot(self, *, run_id: str) -> dict[str, Any]:
        safe_run_id = str(run_id or "").strip()
        if not safe_run_id:
            return {"session_shared": {}, "agent_private": {}, "history_shared": []}

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT scope, profile_id, worker_id, mkey, mvalue
                FROM memory_entries
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (safe_run_id,),
            ).fetchall()

        session_shared: dict[str, list[str]] = {}
        agent_private: dict[str, dict[str, dict[str, list[str]]]] = {}
        history_shared: list[str] = []
        for row in rows:
            scope = str(row["scope"] or "").strip()
            key = str(row["mkey"] or "").strip()
            value = str(row["mvalue"] or "").strip()
            if not key or not value:
                continue
            if scope == "session_shared":
                session_shared.setdefault(key, []).append(value)
            elif scope == "agent_private":
                profile_id = str(row["profile_id"] or "").strip()
                worker_id = self._normalize_worker_id(str(row["worker_id"] or ""))
                agent_private.setdefault(profile_id, {}).setdefault(worker_id, {}).setdefault(key, []).append(value)
            elif scope == "history_shared":
                history_shared.append(value)

        return {
            "session_shared": session_shared,
            "agent_private": agent_private,
            "history_shared": history_shared,
        }

    def clear_run(self, *, run_id: str) -> None:
        safe_run_id = str(run_id or "").strip()
        if not safe_run_id:
            return
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM memory_entries WHERE run_id = ?",
                (safe_run_id,),
            )

    def clone_session_view(self, *, run_id: str) -> dict[str, list[str]]:
        return deepcopy(self.build_session_view(run_id=run_id))
