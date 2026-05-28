from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TokenUsage:
    """Aggregated token usage for a traced session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        self.prompt_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        explicit_total = usage.get("total_tokens")
        if explicit_total is not None:
            self.total_tokens += int(explicit_total)
        else:
            self.total_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            self.total_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        data = data or {}
        return cls(
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            completion_tokens=int(data.get("completion_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
        )


@dataclass
class SessionTrace:
    """Summary row for one traced agent session."""

    session_id: str
    agent_id: str = ""
    status: str = "running"
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    event_count: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "event_count": self.event_count,
            "token_usage": self.token_usage.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionTrace":
        return cls(
            session_id=data["session_id"],
            agent_id=data.get("agent_id", ""),
            status=data.get("status", "running"),
            started_at=_parse_dt(data.get("started_at")) or datetime.now(),
            ended_at=_parse_dt(data.get("ended_at")),
            event_count=int(data.get("event_count", 0)),
            token_usage=TokenUsage.from_dict(data.get("token_usage")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class EventTrace:
    """A persistable, JSON-friendly representation of one EventBus event."""

    event_id: str
    session_id: str
    event_type: str
    timestamp: datetime
    agent_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "agent_id": self.agent_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventTrace":
        return cls(
            event_id=data["event_id"],
            session_id=data.get("session_id", ""),
            event_type=data["event_type"],
            timestamp=_parse_dt(data.get("timestamp")) or datetime.now(),
            agent_id=data.get("agent_id", ""),
            payload=dict(data.get("payload") or {}),
        )


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None
