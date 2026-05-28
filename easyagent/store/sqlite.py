from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from easyagent.tracing.schema import EventTrace, SessionTrace


class SQLiteStore:
    """SQLite-backed trace store for local dashboards and history."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def upsert_session(self, session: SessionTrace) -> None:
        data = session.to_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, agent_id, status, started_at, ended_at,
                    event_count, token_usage, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_id=excluded.agent_id,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    event_count=excluded.event_count,
                    token_usage=excluded.token_usage,
                    metadata=excluded.metadata
                """,
                (
                    data["session_id"],
                    data["agent_id"],
                    data["status"],
                    data["started_at"],
                    data["ended_at"],
                    data["event_count"],
                    json.dumps(data["token_usage"]),
                    json.dumps(data["metadata"], ensure_ascii=False),
                ),
            )

    def append_event(self, event: EventTrace) -> None:
        data = event.to_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO events (
                    event_id, session_id, event_type, timestamp, agent_id, payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["session_id"],
                    data["event_type"],
                    data["timestamp"],
                    data["agent_id"],
                    json.dumps(data["payload"], ensure_ascii=False, default=str),
                ),
            )

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionTrace]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> SessionTrace | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._session_from_row(row) if row else None

    def list_events(self, session_id: str) -> list[EventTrace]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def trace_signature(self) -> tuple[int, int, int]:
        """Return a compact signature for polling readers."""

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS event_count,
                    COALESCE(MAX(id), 0) AS max_event_id,
                    (SELECT COUNT(*) FROM sessions) AS session_count
                FROM events
                """
            ).fetchone()
        return (row["session_count"], row["event_count"], row["max_event_id"])

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    token_usage TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id)")

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionTrace:
        return SessionTrace.from_dict(
            {
                "session_id": row["session_id"],
                "agent_id": row["agent_id"],
                "status": row["status"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "event_count": row["event_count"],
                "token_usage": json.loads(row["token_usage"] or "{}"),
                "metadata": json.loads(row["metadata"] or "{}"),
            }
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> EventTrace:
        return EventTrace.from_dict(
            {
                "event_id": row["event_id"],
                "session_id": row["session_id"],
                "event_type": row["event_type"],
                "timestamp": row["timestamp"],
                "agent_id": row["agent_id"],
                "payload": json.loads(row["payload"] or "{}"),
            }
        )
