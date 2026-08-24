from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from easyagent.events.base import BaseEvent


AgentId = str
BROADCAST: Literal["*"] = "*"


# ── Wait: agent requests to be called again next tick ────────────────────────

@dataclass
class WaitEvent(BaseEvent):
    """Returned by ``session.step`` to say "I pass this tick, but wake me next tick."

    The Runtime does NOT publish this to the bus — it just schedules a
    re-delivery for the agent next tick. Other agents never see it.
    """

    agent_id: AgentId = ""


# ── Stop: external request to break a session's running loop ─────────────────

@dataclass
class StopEvent(BaseEvent):
    """Passive notification that a session stop was requested.

    Publishing an Event cannot change execution. Use
    ``AgentSession.request_stop(...)`` for control, then publish this event
    separately if observers also need a notification.

    ``session_id`` selects the target. ``data`` is whatever payload the
    sender wants to expose to observers.
    """

    session_id: AgentId = ""
    reason: str = ""
    data: Any = None


# ── Message: the only communication primitive ────────────────────────────────

@dataclass
class MessageEvent(BaseEvent):
    """An agent speaking.

    ``to`` carries the visibility rule directly on the message:
      - ``"*"``                  broadcast (everyone on the runtime sees it)
      - ``"bob"``                direct message (single recipient, normalized to a frozenset)
      - ``frozenset({"a","b"})`` sub-group (also accepts ``set`` / ``list`` / ``tuple``)

    Convenient input forms get normalized in ``__post_init__`` to either
    the ``"*"`` literal or a ``frozenset[AgentId]`` for downstream code
    to pattern-match on without re-parsing.

    There is no separate "Channel" object — group membership lives on the
    message itself. Persistent rooms/threads are expressed via ``metadata``.
    """

    sender: AgentId = ""
    content: str = ""
    to: (
        Literal["*"]
        | AgentId
        | frozenset[AgentId]
        | set[AgentId]
        | list[AgentId]
        | tuple[AgentId, ...]
    ) = BROADCAST
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce convenient input forms into the canonical types:
        #   "*"            -> stays as "*"          (broadcast sentinel)
        #   "alice"        -> frozenset({"alice"})  (single recipient — common typo)
        #   {"a","b"}      -> frozenset({"a","b"})
        #   ["a","b"]      -> frozenset({"a","b"})
        if isinstance(self.to, str):
            if self.to != BROADCAST:
                self.to = frozenset({self.to})
        elif isinstance(self.to, (set, list, tuple)):
            self.to = frozenset(self.to)

    @property
    def is_broadcast(self) -> bool:
        return self.to == BROADCAST

    def visible_to(self, agent_id: AgentId) -> bool:
        if self.is_broadcast:
            return True
        assert isinstance(self.to, frozenset)
        return agent_id in self.to


@dataclass
class CustomTraceEvent(BaseEvent):
    """User-defined event that can be persisted and projected in dashboards.

    ``event_type`` becomes the persisted trace event type. ``payload`` stores
    arbitrary JSON-friendly data, and ``display`` optionally tells dashboards
    where and how to render the event.
    """

    event_type: str = "CustomTraceEvent"
    session_id: str = ""
    agent_id: AgentId = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    display: Any = None


# ── Lifecycle events (optional telemetry; not required for core loop) ────────

@dataclass
class RuntimeStartedEvent(BaseEvent):
    run_id: str = ""
    run_title: str = ""
    agent_ids: list[AgentId] = field(default_factory=list)
    world: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeFinishedEvent(BaseEvent):
    run_id: str = ""
    reason: str = ""
    status: str = "completed"
    ticks: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeTickStartedEvent(BaseEvent):
    run_id: str = ""
    tick: int = 0
    active_entities: list[AgentId] = field(default_factory=list)


@dataclass
class RuntimeTickFinishedEvent(BaseEvent):
    run_id: str = ""
    tick: int = 0
    action_count: int = 0


@dataclass
class EntityStartedEvent(BaseEvent):
    run_id: str = ""
    entity_id: AgentId = ""
    tick: int = 0


@dataclass
class EntityFinishedEvent(BaseEvent):
    run_id: str = ""
    entity_id: AgentId = ""
    tick: int = 0
    action_type: str = ""


@dataclass
class AgentStartedEvent(BaseEvent):
    agent_id: AgentId = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentFinishedEvent(BaseEvent):
    agent_id: AgentId = ""
    output: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentFailedEvent(BaseEvent):
    agent_id: AgentId = ""
    error: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolCalledEvent(BaseEvent):
    agent_id: AgentId = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultEvent(BaseEvent):
    agent_id: AgentId = ""
    tool_name: str = ""
    result: str = ""
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCalledEvent(BaseEvent):
    agent_id: AgentId = ""
    model: str = ""
    message_count: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LLMRespondedEvent(BaseEvent):
    agent_id: AgentId = ""
    model: str = ""
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMStreamChunkEvent(BaseEvent):
    agent_id: AgentId = ""
    model: str = ""
    content: str = ""
    sequence: int = 0
