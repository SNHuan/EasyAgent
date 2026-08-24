from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Lock

from easyagent.checkpoint.schema import AgentCheckpoint


class SQLiteCheckpointStore:
    """Durable SQLite adapter for the latest checkpoint per session."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._initialized = False
        self._init_lock = Lock()

    async def save(self, checkpoint: AgentCheckpoint) -> None:
        await asyncio.to_thread(self._save, checkpoint)

    async def load(self, session_id: str) -> AgentCheckpoint | None:
        return await asyncio.to_thread(self._load, session_id)

    def _save(
        self,
        checkpoint: AgentCheckpoint,
    ) -> None:
        payload = json.dumps(
            checkpoint.to_dict(),
            ensure_ascii=False,
        )
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO agent_checkpoints (
                    session_id, payload
                )
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    payload=excluded.payload
                """,
                (
                    checkpoint.session_id,
                    payload,
                ),
            )

    def _load(self, session_id: str) -> AgentCheckpoint | None:
        self._ensure_initialized()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT payload
                FROM agent_checkpoints
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return AgentCheckpoint.from_dict(json.loads(row["payload"]))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_checkpoints (
                        session_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                    """
                )
            self._initialized = True
