from __future__ import annotations

import inspect
import uuid
from typing import Any, Callable

from easyagent.core.types import Action, MessagesSlice, Perception, Speak
from easyagent.events import CustomTraceEvent, EventBus
from easyagent.external.base import ExternalEventHandler, ExternalResult, ExternalRunner
from easyagent.tracing import DisplayHint


InputMapper = Callable[[Perception], str]
OutputMapper = Callable[[ExternalResult], Action | None]


class ExternalAgentEntity:
    """Wrap an externally managed agent runner as a Runtime Entity.

    The runner owns provider-specific capabilities, permissions, tools, and
    sessions. EasyAgent only maps Runtime perception into a prompt, invokes the
    runner, maps its result back to an action, and emits trace events.
    """

    def __init__(
        self,
        id: str,
        *,
        runner: ExternalRunner,
        provider: str = "external",
        name: str | None = None,
        input_mapper: InputMapper | None = None,
        output_mapper: OutputMapper | None = None,
        trace_level: str = "summary",
    ) -> None:
        self._id = id
        self.runner = runner
        self.provider = provider
        self.name = name or id
        self.input_mapper = input_mapper or default_input_mapper
        self.output_mapper = output_mapper or default_output_mapper
        self.trace_level = trace_level
        self.provider_session_id: str | None = None
        self._runtime_context: dict[str, Any] = {}

    @property
    def id(self) -> str:
        return self._id

    def bind_runtime_context(
        self,
        *,
        run_id: str,
        run_title: str,
        world: dict[str, object],
        entity: dict[str, object],
        bus: EventBus | None,
    ) -> None:
        self._runtime_context = {
            "run_id": run_id,
            "run_title": run_title,
            "world": world,
            "entity": entity,
            "bus": bus,
        }

    async def act(self, perception: Perception) -> Action | None:
        prompt = self.input_mapper(perception)
        session_id = self._new_trace_session_id()
        metadata = self._runner_metadata(perception, session_id)
        await self._publish_started(session_id, prompt)
        sequence = 0

        async def event_handler(event: dict[str, Any]) -> None:
            nonlocal sequence
            sequence += 1
            await self._publish_provider_event(
                session_id,
                self.provider,
                sequence,
                event,
            )

        try:
            raw_result = await self._run_external(prompt, metadata, event_handler)
        except Exception as exc:
            await self._publish_failed(session_id, exc)
            raise

        result = self._coerce_result(raw_result)
        if result.session_id:
            self.provider_session_id = result.session_id
        await self._publish_provider_events(session_id, result, start_sequence=sequence)
        await self._publish_finished(session_id, result)
        return self.output_mapper(result)

    async def _run_external(
        self,
        prompt: str,
        metadata: dict[str, Any],
        event_handler: ExternalEventHandler,
    ) -> str | ExternalResult:
        run = self.runner.run
        try:
            signature = inspect.signature(run)
        except (TypeError, ValueError):
            return await run(prompt, metadata=metadata, event_handler=event_handler)
        kwargs: dict[str, Any] = {}
        if "metadata" in signature.parameters:
            kwargs["metadata"] = metadata
        if "event_handler" in signature.parameters:
            kwargs["event_handler"] = event_handler
        if kwargs:
            return await run(prompt, **kwargs)
        return await run(prompt)  # type: ignore[call-arg]

    def _coerce_result(self, raw_result: str | ExternalResult) -> ExternalResult:
        if isinstance(raw_result, ExternalResult):
            if not raw_result.provider or raw_result.provider == "external":
                raw_result.provider = self.provider
            return raw_result
        return ExternalResult(content=str(raw_result), provider=self.provider)

    def _new_trace_session_id(self) -> str:
        run_id = self._runtime_context.get("run_id")
        if run_id:
            return f"{run_id}:{self._id}:{uuid.uuid4().hex}"
        return f"{self._id}:{uuid.uuid4().hex}"

    def _runner_metadata(self, perception: Perception, trace_session_id: str) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "entity_id": self._id,
            "trace_session_id": trace_session_id,
            "provider_session_id": self.provider_session_id,
            "tick": perception.tick,
            **self._runtime_metadata(),
        }

    def _runtime_metadata(self) -> dict[str, Any]:
        if not self._runtime_context:
            return {}
        return {
            "run_id": self._runtime_context.get("run_id"),
            "run_scope": "runtime",
            "run_title": self._runtime_context.get("run_title"),
            "world": self._runtime_context.get("world"),
            "entity": self._runtime_context.get("entity"),
        }

    async def _publish_started(self, session_id: str, prompt: str) -> None:
        bus = self._bus()
        if bus is None:
            return
        await bus.publish(
            CustomTraceEvent(
                event_type="ExternalAgentStartedEvent",
                session_id=session_id,
                agent_id=self._id,
                summary=f"{self.provider} external agent started",
                payload={
                    "provider": self.provider,
                    "prompt": _truncate(prompt, 8_000),
                    **self._trace_payload_metadata(),
                },
                display=DisplayHint.timeline(
                    f"{self.provider} started",
                    title="External agent started",
                ),
            )
        )

    async def _publish_finished(self, session_id: str, result: ExternalResult) -> None:
        bus = self._bus()
        if bus is None:
            return
        await bus.publish(
            CustomTraceEvent(
                event_type="ExternalAgentFinishedEvent",
                session_id=session_id,
                agent_id=self._id,
                summary=_truncate(result.content, 240),
                payload={
                    "provider": result.provider,
                    "provider_session_id": result.session_id,
                    "content": result.content,
                    "usage": result.usage,
                    "events": _events_for_trace(result.events, self.trace_level),
                    "artifacts": result.artifacts,
                    "metadata": result.metadata,
                    **self._trace_payload_metadata(result),
                },
                display=DisplayHint.messages(
                    result.content,
                    role="assistant",
                    title=f"{result.provider} result",
                    source=result.provider,
                ),
            )
        )

    async def _publish_provider_events(
        self,
        session_id: str,
        result: ExternalResult,
        *,
        start_sequence: int = 0,
    ) -> None:
        for index, event in enumerate(result.events, start=start_sequence + 1):
            await self._publish_provider_event(session_id, result.provider, index, event, result)

    async def _publish_provider_event(
        self,
        session_id: str,
        provider: str,
        sequence: int,
        event: dict[str, Any],
        result: ExternalResult | None = None,
    ) -> None:
        bus = self._bus()
        if bus is None:
            return
        event_type, payload, display = _provider_event_trace(provider, event)
        await bus.publish(
            CustomTraceEvent(
                event_type=event_type,
                session_id=session_id,
                agent_id=self._id,
                summary=str(payload.get("summary") or payload.get("content") or event_type),
                payload={
                    "provider": provider,
                    "sequence": sequence,
                    **payload,
                    **self._trace_payload_metadata(result),
                },
                display=display,
            )
        )

    async def _publish_failed(self, session_id: str, exc: Exception) -> None:
        bus = self._bus()
        if bus is None:
            return
        await bus.publish(
            CustomTraceEvent(
                event_type="ExternalAgentFailedEvent",
                session_id=session_id,
                agent_id=self._id,
                summary=str(exc),
                payload={
                    "provider": self.provider,
                    "error": str(exc),
                    **self._trace_payload_metadata(),
                },
                display=DisplayHint.timeline(
                    str(exc),
                    title="External agent failed",
                ),
            )
        )

    def _trace_payload_metadata(self, result: ExternalResult | None = None) -> dict[str, Any]:
        metadata = {
            "trace_kind": "external_agent",
            "provider": self.provider,
            "provider_session_id": self.provider_session_id,
            **self._runtime_metadata(),
        }
        if result and result.session_id:
            metadata["provider_session_id"] = result.session_id
        if result and "dashboard_group_path" in result.metadata:
            metadata["dashboard_group_path"] = result.metadata["dashboard_group_path"]
        return metadata

    def _bus(self) -> EventBus | None:
        bus = self._runtime_context.get("bus")
        return bus if isinstance(bus, EventBus) else None


def default_input_mapper(perception: Perception) -> str:
    messages = perception.of_type(MessagesSlice)
    if messages is None or not messages.messages:
        return ""
    return "\n".join(f"[{message.sender}] {message.content}" for message in messages.messages)


def default_output_mapper(result: ExternalResult) -> Action | None:
    if not result.content.strip():
        return None
    return Speak(content=result.content)


def _events_for_trace(events: list[dict[str, Any]], trace_level: str) -> list[dict[str, Any]]:
    if trace_level == "debug":
        return events
    if trace_level == "events":
        return events[:200]
    return []


def _truncate(value: str, max_length: int) -> str:
    return value if len(value) <= max_length else f"{value[:max_length]}... [truncated]"


def _provider_event_trace(
    provider: str,
    event: dict[str, Any],
) -> tuple[str, dict[str, Any], DisplayHint]:
    event_kind = str(event.get("type") or "provider")
    if event_kind == "message":
        content = str(event.get("content") or event.get("summary") or "")
        role = str(event.get("role") or "assistant")
        if role not in {"system", "user", "assistant", "tool"}:
            role = "assistant"
        return (
            "ExternalAgentMessageEvent",
            {"content": content, "role": role, "raw_event": event},
            DisplayHint.messages(
                content,
                role=role,  # type: ignore[arg-type]
                title=f"{provider} message",
                source=provider,
            ),
        )
    if event_kind == "message_delta":
        content = str(event.get("content") or event.get("delta") or "")
        role = str(event.get("role") or "assistant")
        if role not in {"system", "user", "assistant", "tool"}:
            role = "assistant"
        return (
            "ExternalAgentMessageDeltaEvent",
            {"content": content, "role": role, "raw_event": event},
            DisplayHint.hidden(),
        )
    if event_kind == "tool_call":
        tool_name = str(event.get("name") or event.get("tool_name") or "tool")
        return (
            "ExternalAgentToolCallEvent",
            {
                "tool_name": tool_name,
                "arguments": event.get("arguments") or event.get("input") or {},
                "raw_event": event,
            },
            DisplayHint.timeline(
                tool_name,
                title=f"{provider} tool call",
            ),
        )
    if event_kind == "tool_result":
        tool_name = str(event.get("name") or event.get("tool_name") or "tool")
        content = str(event.get("content") or event.get("result") or "")
        return (
            "ExternalAgentToolResultEvent",
            {
                "tool_name": tool_name,
                "content": content,
                "is_error": event.get("is_error"),
                "raw_event": event,
            },
            DisplayHint.timeline(
                _truncate(content, 240),
                title=f"{provider} tool result",
            ),
        )
    return (
        "ExternalAgentProviderEvent",
        {"summary": str(event.get("summary") or event_kind), "raw_event": event},
        DisplayHint.timeline(
            str(event.get("summary") or event_kind),
            title=f"{provider} event",
        ),
    )
