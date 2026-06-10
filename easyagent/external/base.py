from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable


ExternalEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class ExternalResult:
    """Provider-neutral result returned by an external agent runner."""

    content: str
    provider: str = "external"
    session_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExternalRunner(Protocol):
    """Minimal protocol for wrapping hosted/managed agent SDKs."""

    async def run(
        self,
        prompt: str,
        *,
        metadata: dict[str, Any] | None = None,
        event_handler: ExternalEventHandler | None = None,
    ) -> str | ExternalResult:
        ...
