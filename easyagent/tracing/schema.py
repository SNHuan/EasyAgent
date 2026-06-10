from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


TokenUsageAdapter = Callable[[dict[str, Any]], dict[str, Any]]
_TOKEN_USAGE_ADAPTERS: dict[str, TokenUsageAdapter] = {}


def register_token_usage_adapter(provider: str, adapter: TokenUsageAdapter) -> None:
    """Register a provider-specific token usage normalizer.

    Adapters receive the provider's raw usage payload and should return
    EasyAgent's normalized shape: ``prompt_tokens``, ``completion_tokens``,
    ``total_tokens``, and optionally ``details``.
    """

    _TOKEN_USAGE_ADAPTERS[provider] = adapter


@dataclass
class TokenUsage:
    """Aggregated token usage for a traced session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    details: dict[str, int] = field(default_factory=dict)

    def add(self, usage: dict[str, Any] | None, *, provider: str | None = None) -> None:
        if not usage:
            return
        normalized = normalize_token_usage(usage, provider=provider)
        self.prompt_tokens += int(normalized.get("prompt_tokens") or 0)
        self.completion_tokens += int(normalized.get("completion_tokens") or 0)
        self.total_tokens += int(normalized.get("total_tokens") or 0)
        details = normalized.get("details")
        if isinstance(details, dict):
            for key, value in details.items():
                self.details[key] = self.details.get(key, 0) + int(value or 0)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.details:
            data["details"] = self.details
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        data = data or {}
        return cls(
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            completion_tokens=int(data.get("completion_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            details={key: int(value or 0) for key, value in dict(data.get("details") or {}).items()},
        )


def normalize_token_usage(usage: dict[str, Any], *, provider: str | None = None) -> dict[str, Any]:
    adapter = _TOKEN_USAGE_ADAPTERS.get(provider or "")
    if adapter is not None:
        return adapter(usage)
    return _default_token_usage_adapter(usage)


def _default_token_usage_adapter(usage: dict[str, Any]) -> dict[str, Any]:
    source = usage.get("total") if isinstance(usage.get("total"), dict) else usage
    prompt_tokens = _int_token(source.get("prompt_tokens") or source.get("input_tokens"))
    completion_tokens = _int_token(source.get("completion_tokens") or source.get("output_tokens"))
    reasoning_tokens = _int_token(source.get("reasoning_output_tokens") or source.get("reasoning_tokens"))
    explicit_total = source.get("total_tokens")
    total_tokens = _int_token(explicit_total) if explicit_total is not None else prompt_tokens + completion_tokens + reasoning_tokens
    details: dict[str, int] = {}
    cached_input_tokens = _int_token(source.get("cached_input_tokens") or source.get("cached_tokens"))
    if cached_input_tokens:
        details["cached_input_tokens"] = cached_input_tokens
    cache_creation_input_tokens = _int_token(source.get("cache_creation_input_tokens"))
    if cache_creation_input_tokens:
        details["cache_creation_input_tokens"] = cache_creation_input_tokens
    cache_read_input_tokens = _int_token(source.get("cache_read_input_tokens"))
    if cache_read_input_tokens:
        details["cache_read_input_tokens"] = cache_read_input_tokens
    if reasoning_tokens:
        details["reasoning_output_tokens"] = reasoning_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens + reasoning_tokens,
        "total_tokens": total_tokens,
        "details": details,
    }


def _int_token(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
