from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from inspect import signature
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


@dataclass(frozen=True, slots=True)
class ExternalRunRequest:
    """Provider-neutral input for one external-agent turn."""

    prompt: str
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExternalRunner(Protocol):
    """Minimal protocol for wrapping hosted/managed agent SDKs."""

    async def run_request(
        self,
        request: ExternalRunRequest,
        *,
        event_handler: ExternalEventHandler | None = None,
    ) -> str | ExternalResult:
        ...


class LegacyExternalRunnerAdapter:
    """Adapt legacy ``run(prompt, ...)`` runners to ``ExternalRunner``."""

    def __init__(self, runner: Any) -> None:
        if not callable(getattr(runner, "run", None)):
            raise TypeError("Legacy external runner must define async run(prompt, ...)")
        self.runner = runner

    async def run_request(
        self,
        request: ExternalRunRequest,
        *,
        event_handler: ExternalEventHandler | None = None,
    ) -> str | ExternalResult:
        run = self.runner.run
        try:
            parameters = signature(run).parameters
        except (TypeError, ValueError):
            return await run(request.prompt)

        kwargs: dict[str, Any] = {}
        if "metadata" in parameters:
            kwargs["metadata"] = request.metadata
        if "event_handler" in parameters:
            kwargs["event_handler"] = event_handler
        return await run(request.prompt, **kwargs)
