from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from easyagent.tracing.schema import EventTrace, SessionTrace


class JSONLStore:
    """Append-only JSONL trace store.

    This is intentionally simple and human-inspectable. Each line is either a
    session snapshot or one event.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_session(self, session: SessionTrace) -> None:
        self._append({"kind": "session", "data": session.to_dict()})

    def append_event(self, event: EventTrace) -> None:
        self._append({"kind": "event", "data": event.to_dict()})

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionTrace]:
        sessions = list(self._read_sessions().values())
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions[offset: offset + limit]

    def get_session(self, session_id: str) -> SessionTrace | None:
        return self._read_sessions().get(session_id)

    def list_events(self, session_id: str) -> list[EventTrace]:
        return [
            EventTrace.from_dict(row["data"])
            for row in self._read_rows()
            if row.get("kind") == "event" and row.get("data", {}).get("session_id") == session_id
        ]

    def _append(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str))
            f.write("\n")

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def _read_sessions(self) -> dict[str, SessionTrace]:
        sessions: dict[str, SessionTrace] = {}
        for row in self._read_rows():
            if row.get("kind") != "session":
                continue
            session = SessionTrace.from_dict(row["data"])
            sessions[session.session_id] = session
        return sessions
