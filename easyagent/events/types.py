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
    """Ask a specific session to terminate its in-flight loop early.

    Anyone can publish this (the session's own tools, a supervisor agent,
    external control code, …). Each session is auto-subscribed at spawn
    time to a bus listener that translates a matching StopEvent into
    ``session.loop_state["__early_exit__"] = data``. The next tool/loop
    boundary in :class:`ReActLoop` then breaks out and returns ``data``
    as the loop's final output.

    ``session_id`` selects the target. ``data`` is whatever payload the
    sender wants the loop to surface as its final output (typically a
    handoff summary, but it can be anything string-coercible).
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


# ── Lifecycle events (optional telemetry; not required for core loop) ────────

@dataclass
class RuntimeStartedEvent(BaseEvent):
    agent_ids: list[AgentId] = field(default_factory=list)


@dataclass
class RuntimeFinishedEvent(BaseEvent):
    reason: str = ""


@dataclass
class AgentStartedEvent(BaseEvent):
    agent_id: AgentId = ""


@dataclass
class AgentFinishedEvent(BaseEvent):
    agent_id: AgentId = ""
    output: str = ""


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


@dataclass
class LLMCalledEvent(BaseEvent):
    agent_id: AgentId = ""
    model: str = ""
    message_count: int = 0


@dataclass
class LLMRespondedEvent(BaseEvent):
    agent_id: AgentId = ""
    model: str = ""
    content: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
