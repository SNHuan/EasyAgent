from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Mapping, Protocol, runtime_checkable

from easyagent.events.base import BaseEvent
from easyagent.events.types import AgentId, MessageEvent

if TYPE_CHECKING:
    from easyagent.agent.session import AgentSession
    from easyagent.runtime.state import RuntimeState


SessionId = AgentId
Delivery = tuple[SessionId, BaseEvent]


@runtime_checkable
class StepPolicy(Protocol):
    """Decides which sessions process an event."""

    def deliveries(
        self,
        event: BaseEvent,
        sessions: Mapping[SessionId, "AgentSession"],
        state: "RuntimeState",
    ) -> list[Delivery]: ...


@runtime_checkable
class StopPolicy(Protocol):
    """Decides when the runtime should halt."""

    def should_stop(self, state: "RuntimeState") -> tuple[bool, str]: ...


@runtime_checkable
class SchedulePolicy(Protocol):
    """Decides execution batches inside one tick."""

    def order(
        self,
        session_ids: list[SessionId],
        state: "RuntimeState",
    ) -> list[list[SessionId]]: ...


# ── Step policies ───────────────────────────────────────────────────────────


@dataclass
class DeliverToRecipients:
    """The canonical "group chat" policy.

    - MessageEvent: delivered only to sessions listed in ``to`` (or all on
      ``"*"``). The sender does NOT receive its own message.
    - Other BaseEvent: delivered to every session, so user-defined events
      (TimerTick, WeatherChanged, ...) reach everyone by default.
    """

    deliver_non_messages_to_all: bool = True

    def deliveries(
        self,
        event: BaseEvent,
        sessions: Mapping[SessionId, "AgentSession"],
        state: "RuntimeState",
    ) -> list[Delivery]:
        if isinstance(event, MessageEvent):
            if event.is_broadcast:
                return [(sid, event) for sid in sessions if sid != event.sender]
            return [
                (sid, event)
                for sid in sessions
                if sid != event.sender and event.visible_to(sid)
            ]
        if self.deliver_non_messages_to_all:
            return [(sid, event) for sid in sessions]
        return []

    def deliveries_on_tick(self, sessions, state):  # noqa: ARG002
        return []


@dataclass
class TickDriven:
    """Ignore the event stream; at each tick, every session gets a synthetic
    "TickEvent" so it can introspect the bus and decide whether to speak.

    Use this for social simulations where sessions should have the chance to
    act even when no one is messaging them.
    """

    def deliveries(self, event, sessions, state):  # noqa: ARG002
        return []

    def deliveries_on_tick(
        self,
        sessions: Mapping[SessionId, "AgentSession"],
        state: "RuntimeState",
    ) -> list[Delivery]:
        tick_event = _TickEvent(tick=state.tick)
        return [(sid, tick_event) for sid in sessions]


class _TickEvent(BaseEvent):
    """Opaque signal that a new tick has begun. Consumed by TickDriven."""

    def __init__(self, tick: int):
        super().__init__()
        self.tick = tick


# ── Schedule policies ────────────────────────────────────────────────────────


@dataclass
class Parallel:
    """All sessions in this tick run concurrently in one batch.

    Fast, but sessions in the same tick can't see each other's outputs —
    they only see them next tick (cross-posting).
    """

    def order(self, session_ids: list[SessionId], state: "RuntimeState") -> list[list[SessionId]]:
        return [list(session_ids)] if session_ids else []


@dataclass
class Sequential:
    """Sessions run one by one in the order ``session_ids`` was given.

    Each session's output is immediately visible to the sessions scheduled
    after it within the same tick. Deterministic and predictable.
    """

    def order(self, session_ids: list[SessionId], state: "RuntimeState") -> list[list[SessionId]]:
        return [[sid] for sid in session_ids]


@dataclass
class Shuffled:
    """Sessions run one by one in a random order each tick.

    Like ``Sequential``, earlier sessions' outputs are visible to later ones.
    The random order simulates "who happens to check the chat first" — the
    most realistic mode for social simulation.
    """

    def order(self, session_ids: list[SessionId], state: "RuntimeState") -> list[list[SessionId]]:
        shuffled = list(session_ids)
        random.shuffle(shuffled)
        return [[sid] for sid in shuffled]


# ── Stop policies ────────────────────────────────────────────────────────────


@dataclass
class StopWhenIdle:
    """Stop once a full step produces no new events.

    `grace_steps` lets the runtime sit idle for N steps before giving up —
    useful when you've only seeded an initial message and want every agent
    to get a first look.
    """

    grace_steps: int = 1

    def should_stop(self, state: "RuntimeState") -> tuple[bool, str]:
        if state.idle_steps > self.grace_steps:
            return True, "idle"
        return False, ""


@dataclass
class StopAfterTicks:
    max_ticks: int

    def should_stop(self, state: "RuntimeState") -> tuple[bool, str]:
        state.max_ticks = self.max_ticks
        if state.tick > self.max_ticks:
            return True, f"reached max_ticks={self.max_ticks}"
        return False, ""


@dataclass
class StopAfterEvents:
    """Hard cap on total events (belt-and-suspenders against runaway loops)."""

    max_events: int

    def should_stop(self, state: "RuntimeState") -> tuple[bool, str]:
        if len(state.events) >= self.max_events:
            return True, f"reached max_events={self.max_events}"
        return False, ""


@dataclass
class StopWhenMessageMatches:
    """Stop when some message matches a user-provided predicate.

    Typical use: an agent signals completion with metadata={"done": True}.
    """

    predicate: Callable[[MessageEvent], bool]

    def should_stop(self, state: "RuntimeState") -> tuple[bool, str]:
        for event in reversed(state.events):
            if isinstance(event, MessageEvent) and self.predicate(event):
                return True, f"message matched (sender={event.sender})"
        return False, ""


@dataclass
class AnyOf:
    """Compose stop policies — halt when any one of them fires."""

    policies: list[object] = field(default_factory=list)

    def should_stop(self, state: "RuntimeState") -> tuple[bool, str]:
        for policy in self.policies:
            stop, reason = policy.should_stop(state)  # type: ignore[attr-defined]
            if stop:
                return True, reason
        return False, ""
