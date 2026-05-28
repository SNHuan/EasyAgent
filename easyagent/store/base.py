from __future__ import annotations

from typing import Protocol

from easyagent.tracing.schema import EventTrace, SessionTrace


class TraceStore(Protocol):
    """Storage interface for agent session traces."""

    def upsert_session(self, session: SessionTrace) -> None:
        ...

    def append_event(self, event: EventTrace) -> None:
        ...

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionTrace]:
        ...

    def get_session(self, session_id: str) -> SessionTrace | None:
        ...

    def list_events(self, session_id: str) -> list[EventTrace]:
        ...
