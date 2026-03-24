from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import sqlite3
from typing import Any

from core.settings import get_settings


@dataclass(frozen=True)
class RuntimeTaskExecutionRecord:
    session_id: str
    user_id: str
    task_kind: str
    agent_id: str
    profile: str
    contract_id: str
    round_index: int
    confidence: float
    estimated_latency_ms: int
    estimated_cost: float
    elapsed_ms: int
    approved: bool
    critic_reason: str
    critic_severity: str
    realized_cost: float


class RuntimeEvaluationService:
    """Persistent runtime evaluation store used for online scoring and offline analysis."""

    def __init__(self, *, db_path: str | None = None) -> None:
        settings = get_settings()
        configured_path = str(db_path or (getattr(settings, "runtime_eval_db_path", "") or "")).strip()
        if configured_path:
            self.db_path = Path(configured_path).expanduser().resolve()
        else:
            self.db_path = Path(__file__).resolve().parents[1] / "cache" / "runtime_evaluation.sqlite3"
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
                CREATE TABLE IF NOT EXISTS runtime_task_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    round_index INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    estimated_latency_ms INTEGER NOT NULL,
                    estimated_cost REAL NOT NULL,
                    elapsed_ms INTEGER NOT NULL,
                    approved INTEGER NOT NULL,
                    critic_reason TEXT NOT NULL,
                    critic_severity TEXT NOT NULL,
                    realized_cost REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_eval_task_agent_time
                ON runtime_task_executions(task_kind, agent_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_eval_user_time
                ON runtime_task_executions(user_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_session_summaries (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_type TEXT NOT NULL,
                    input_value TEXT NOT NULL,
                    quick_mode INTEGER NOT NULL,
                    rounds INTEGER NOT NULL,
                    total_cost REAL NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    history_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL
                )
                """
            )

    def record_task_execution(self, record: RuntimeTaskExecutionRecord) -> None:
        safe_session_id = str(record.session_id or "").strip()
        safe_user_id = str(record.user_id or "").strip()
        safe_task_kind = str(record.task_kind or "").strip().lower()
        safe_agent_id = str(record.agent_id or "").strip()
        if not safe_session_id or not safe_user_id or not safe_task_kind or not safe_agent_id:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_task_executions(
                    session_id,
                    user_id,
                    task_kind,
                    agent_id,
                    profile,
                    contract_id,
                    round_index,
                    confidence,
                    estimated_latency_ms,
                    estimated_cost,
                    elapsed_ms,
                    approved,
                    critic_reason,
                    critic_severity,
                    realized_cost,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_session_id,
                    safe_user_id,
                    safe_task_kind,
                    safe_agent_id,
                    str(record.profile or "").strip(),
                    str(record.contract_id or "").strip(),
                    max(0, int(record.round_index)),
                    float(record.confidence),
                    max(0, int(record.estimated_latency_ms)),
                    max(0.0, float(record.estimated_cost)),
                    max(0, int(record.elapsed_ms)),
                    1 if bool(record.approved) else 0,
                    str(record.critic_reason or "").strip(),
                    str(record.critic_severity or "").strip(),
                    max(0.0, float(record.realized_cost)),
                    now_iso,
                ),
            )

    def record_session_summary(
        self,
        *,
        session_id: str,
        user_id: str,
        status: str,
        input_type: str,
        input_value: str,
        quick_mode: bool,
        rounds: int,
        total_cost: float,
        duration_ms: int,
        history_id: str,
        report_id: str,
        error: str,
    ) -> None:
        safe_session_id = str(session_id or "").strip()
        safe_user_id = str(user_id or "").strip()
        if not safe_session_id or not safe_user_id:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_session_summaries(
                    session_id,
                    user_id,
                    status,
                    input_type,
                    input_value,
                    quick_mode,
                    rounds,
                    total_cost,
                    duration_ms,
                    history_id,
                    report_id,
                    error,
                    created_at,
                    finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = excluded.status,
                    input_type = excluded.input_type,
                    input_value = excluded.input_value,
                    quick_mode = excluded.quick_mode,
                    rounds = excluded.rounds,
                    total_cost = excluded.total_cost,
                    duration_ms = excluded.duration_ms,
                    history_id = excluded.history_id,
                    report_id = excluded.report_id,
                    error = excluded.error,
                    finished_at = excluded.finished_at
                """,
                (
                    safe_session_id,
                    safe_user_id,
                    str(status or "").strip().lower() or "unknown",
                    str(input_type or "").strip().lower() or "unknown",
                    str(input_value or "").strip(),
                    1 if bool(quick_mode) else 0,
                    max(0, int(rounds)),
                    max(0.0, float(total_cost)),
                    max(0, int(duration_ms)),
                    str(history_id or "").strip(),
                    str(report_id or "").strip(),
                    str(error or "").strip(),
                    now_iso,
                    now_iso,
                ),
            )

    def get_agent_priors(
        self,
        *,
        task_kind: str,
        lookback_days: int = 30,
    ) -> dict[str, dict[str, float]]:
        safe_task_kind = str(task_kind or "").strip().lower()
        if not safe_task_kind:
            return {}
        safe_days = max(1, int(lookback_days))
        threshold = (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    agent_id,
                    COUNT(1) AS sample_size,
                    SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS success_count,
                    AVG(elapsed_ms) AS avg_elapsed_ms,
                    AVG(realized_cost) AS avg_realized_cost,
                    AVG(estimated_latency_ms) AS avg_estimated_latency,
                    AVG(estimated_cost) AS avg_estimated_cost
                FROM runtime_task_executions
                WHERE task_kind = ? AND created_at >= ?
                GROUP BY agent_id
                """,
                (safe_task_kind, threshold),
            ).fetchall()

        result: dict[str, dict[str, float]] = {}
        for row in rows:
            safe_agent_id = str(row["agent_id"] or "").strip()
            if not safe_agent_id:
                continue
            sample_size = max(0, int(row["sample_size"] or 0))
            success_count = max(0, int(row["success_count"] or 0))
            success_rate = float(success_count) / float(sample_size) if sample_size > 0 else 0.0
            result[safe_agent_id] = {
                "sample_size": float(sample_size),
                "success_rate": max(0.0, min(1.0, success_rate)),
                "avg_elapsed_ms": max(0.0, float(row["avg_elapsed_ms"] or 0.0)),
                "avg_realized_cost": max(0.0, float(row["avg_realized_cost"] or 0.0)),
                "avg_estimated_latency": max(0.0, float(row["avg_estimated_latency"] or 0.0)),
                "avg_estimated_cost": max(0.0, float(row["avg_estimated_cost"] or 0.0)),
            }
        return result

    def get_agent_leaderboard(
        self,
        *,
        task_kind: str = "",
        lookback_days: int = 30,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        safe_task_kind = str(task_kind or "").strip().lower()
        safe_days = max(1, int(lookback_days))
        safe_limit = max(1, min(200, int(limit)))
        threshold = (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat()

        if safe_task_kind:
            task_filter = "AND task_kind = ?"
            params: tuple[Any, ...] = (threshold, safe_task_kind, safe_limit)
        else:
            task_filter = ""
            params = (threshold, safe_limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    task_kind,
                    agent_id,
                    COUNT(1) AS sample_size,
                    SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS success_count,
                    AVG(elapsed_ms) AS avg_elapsed_ms,
                    AVG(realized_cost) AS avg_realized_cost,
                    AVG(confidence) AS avg_confidence
                FROM runtime_task_executions
                WHERE created_at >= ? {task_filter}
                GROUP BY task_kind, agent_id
                ORDER BY
                    (CAST(SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS REAL) / COUNT(1)) DESC,
                    AVG(realized_cost) ASC,
                    AVG(elapsed_ms) ASC
                LIMIT ?
                """,
                params,
            ).fetchall()

        leaderboard: list[dict[str, Any]] = []
        for row in rows:
            sample_size = max(0, int(row["sample_size"] or 0))
            success_count = max(0, int(row["success_count"] or 0))
            success_rate = float(success_count) / float(sample_size) if sample_size else 0.0
            leaderboard.append(
                {
                    "task_kind": str(row["task_kind"] or "").strip(),
                    "agent_id": str(row["agent_id"] or "").strip(),
                    "sample_size": sample_size,
                    "success_rate": round(max(0.0, min(1.0, success_rate)), 4),
                    "avg_elapsed_ms": round(max(0.0, float(row["avg_elapsed_ms"] or 0.0)), 2),
                    "avg_realized_cost": round(max(0.0, float(row["avg_realized_cost"] or 0.0)), 4),
                    "avg_confidence": round(max(0.0, min(1.0, float(row["avg_confidence"] or 0.0))), 4),
                }
            )
        return leaderboard


@lru_cache
def get_runtime_evaluation_service() -> RuntimeEvaluationService:
    return RuntimeEvaluationService()
