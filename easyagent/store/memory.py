from __future__ import annotations

from easyagent.tracing.schema import EventTrace, SessionTrace


class MemoryStore:
    """In-process trace store, useful for tests and notebooks."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionTrace] = {}
        self._events: list[EventTrace] = []

    def upsert_session(self, session: SessionTrace) -> None:
        self._sessions[session.session_id] = session

    def append_event(self, event: EventTrace) -> None:
        self._events.append(event)

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionTrace]:
        sessions = sorted(self._sessions.values(), key=lambda s: s.started_at, reverse=True)
        return sessions[offset: offset + limit]

    def get_session(self, session_id: str) -> SessionTrace | None:
        return self._sessions.get(session_id)

    def list_events(self, session_id: str) -> list[EventTrace]:
        return [event for event in self._events if event.session_id == session_id]
