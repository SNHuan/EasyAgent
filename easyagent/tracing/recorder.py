from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from easyagent.events import (
    AgentFailedEvent,
    AgentFinishedEvent,
    AgentStartedEvent,
    BaseEvent,
    CustomTraceEvent,
    EntityFinishedEvent,
    EntityStartedEvent,
    EventBus,
    LLMRespondedEvent,
    MessageEvent,
    RuntimeFinishedEvent,
    RuntimeStartedEvent,
    RuntimeTickFinishedEvent,
    RuntimeTickStartedEvent,
)
from easyagent.tracing.schema import EventTrace, SessionTrace

if TYPE_CHECKING:
    from easyagent.store.base import TraceStore


class TraceRecorder:
    """Subscribe to an EventBus and persist session traces."""

    def __init__(self, store: "TraceStore") -> None:
        self.store = store
        self._sessions: dict[str, SessionTrace] = {}

    def attach(self, bus: EventBus) -> "TraceRecorder":
        bus.subscribe(BaseEvent, self.record)
        return self

    def detach(self, bus: EventBus) -> None:
        bus.unsubscribe(BaseEvent, self.record)

    def record(self, event: BaseEvent) -> None:
        trace = event_to_trace(event)
        session = self._ensure_session(trace)

        if isinstance(event, RuntimeStartedEvent):
            session.status = "running"
            session.started_at = event.timestamp
            session.agent_id = "runtime"
            session.metadata.update(_runtime_metadata(event))
        elif isinstance(event, RuntimeFinishedEvent):
            session.status = event.status
            session.ended_at = event.timestamp
        elif isinstance(event, AgentStartedEvent):
            session.status = "running"
            session.started_at = event.timestamp
            session.agent_id = event.agent_id or session.agent_id
            session.metadata.update(event.metadata)
        elif isinstance(event, AgentFinishedEvent):
            session.status = "completed"
            session.ended_at = event.timestamp
        elif isinstance(event, AgentFailedEvent):
            session.status = "failed"
            session.ended_at = event.timestamp
        elif isinstance(event, LLMRespondedEvent):
            session.token_usage.add(event.usage)
        elif isinstance(event, CustomTraceEvent):
            _apply_custom_trace_session_update(session, event, trace.payload)

        session.event_count += 1
        self.store.append_event(trace)
        self.store.upsert_session(session)

    def _ensure_session(self, event: EventTrace) -> SessionTrace:
        if event.session_id in self._sessions:
            return self._sessions[event.session_id]

        existing = self.store.get_session(event.session_id)
        if existing is not None:
            self._sessions[event.session_id] = existing
            return existing

        session = SessionTrace(
            session_id=event.session_id,
            agent_id=event.agent_id,
            started_at=event.timestamp,
        )
        self._sessions[event.session_id] = session
        self.store.upsert_session(session)
        return session


def event_to_trace(event: BaseEvent) -> EventTrace:
    payload = _event_payload(event)
    session_id = _session_id(event, payload)
    agent_id = str(payload.get("agent_id") or payload.get("sender") or session_id)
    event_type = type(event).__name__
    if isinstance(event, CustomTraceEvent):
        event_type = event.event_type or event_type
        payload = {
            "summary": event.summary,
            **event.payload,
            **({"display": _jsonable(event.display)} if event.display is not None else {}),
        }
    return EventTrace(
        event_id=event.event_id,
        session_id=session_id,
        event_type=event_type,
        timestamp=event.timestamp,
        agent_id=agent_id,
        payload=payload,
    )


def _apply_custom_trace_session_update(
    session: SessionTrace,
    event: CustomTraceEvent,
    payload: dict[str, Any],
) -> None:
    metadata = _custom_trace_metadata(payload)
    if metadata:
        session.metadata.update(metadata)
    if payload.get("trace_kind") == "external_agent":
        if event.event_type.endswith("StartedEvent"):
            session.status = "running"
            session.started_at = event.timestamp
        elif event.event_type.endswith("FinishedEvent"):
            session.status = "completed"
            session.ended_at = event.timestamp
        elif event.event_type.endswith("FailedEvent"):
            session.status = "failed"
            session.ended_at = event.timestamp
    usage = payload.get("usage")
    if isinstance(usage, dict):
        provider = payload.get("provider")
        session.token_usage.add(usage, provider=str(provider) if provider else None)


def _custom_trace_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "trace_kind",
        "run_id",
        "run_scope",
        "run_title",
        "world",
        "entity",
        "dashboard_group_path",
        "provider",
        "provider_session_id",
    ):
        if key in payload:
            metadata[key] = payload[key]
    return metadata


def _session_id(event: BaseEvent, payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata")
    if isinstance(event, _RUNTIME_EVENT_TYPES):
        value = payload.get("run_id")
        if value:
            return str(value)
    if isinstance(event, MessageEvent) and isinstance(metadata, dict) and metadata.get("run_id"):
        return str(metadata["run_id"])
    for key in ("session_id", "agent_id", "sender", "run_id"):
        value = payload.get(key)
        if value:
            return str(value)
    return event.event_id


def _runtime_metadata(event: RuntimeStartedEvent) -> dict[str, Any]:
    return {
        "trace_kind": "runtime",
        "run_id": event.run_id,
        "run_scope": "runtime",
        "run_title": event.run_title,
        "world": event.world,
        "entities": event.entities,
        **event.metadata,
    }


_RUNTIME_EVENT_TYPES = (
    RuntimeStartedEvent,
    RuntimeFinishedEvent,
    RuntimeTickStartedEvent,
    RuntimeTickFinishedEvent,
    EntityStartedEvent,
    EntityFinishedEvent,
)


def _event_payload(event: BaseEvent) -> dict[str, Any]:
    if not is_dataclass(event):
        return {}
    payload: dict[str, Any] = {}
    for field in fields(event):
        if field.name in {"event_id", "timestamp"}:
            continue
        payload[field.name] = _jsonable(getattr(event, field.name))
    return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, (set, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    return value
