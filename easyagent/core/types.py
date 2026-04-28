"""Core data types for the Entity-World-Schedule architecture.

Perception, Action, LoopState, RuntimeResult, and ChatMessage form the
vocabulary that Entity, World, and Schedule implementations speak.
All value types are frozen dataclasses — immutable, hashable, safe to
share across concurrent entity activations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

__all__ = [
    "PerceptionSlice",
    "MessagesSlice",
    "SpatialSlice",
    "StateSlice",
    "Perception",
    "Action",
    "Speak",
    "Move",
    "SetState",
    "Silent",
    "Composite",
    "LoopState",
    "RuntimeResult",
    "ChatMessage",
]


# ── Perception slices ──────────────────────────────────────────────────

_T = TypeVar("_T", bound="PerceptionSlice")


@dataclass(frozen=True)
class PerceptionSlice:
    """Base class for typed perception slices."""


@dataclass(frozen=True)
class MessagesSlice(PerceptionSlice):
    """Conversation history visible to the entity."""

    messages: tuple[ChatMessage, ...] = ()


@dataclass(frozen=True)
class SpatialSlice(PerceptionSlice):
    """Spatial awareness: own position and nearby entity IDs."""

    position: tuple[int, int] = (0, 0)
    nearby: tuple[str, ...] = ()


@dataclass(frozen=True)
class StateSlice(PerceptionSlice):
    """Snapshot of shared key-value state."""

    snapshot: tuple[tuple[str, Any], ...] = ()


# ── Perception ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Perception:
    """Immutable bag of typed slices delivered to an Entity each tick."""

    entity_id: str
    tick: int
    slices: tuple[PerceptionSlice, ...] = ()

    def of_type(self, cls: type[_T]) -> _T | None:
        for s in self.slices:
            if isinstance(s, cls):
                return s
        return None

    def all_of_type(self, cls: type[_T]) -> tuple[_T, ...]:
        return tuple(s for s in self.slices if isinstance(s, cls))


# ── Actions ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Action:
    """Base class for entity actions."""


@dataclass(frozen=True)
class Speak(Action):
    content: str
    to: str | frozenset[str] | Literal["*"] = "*"


@dataclass(frozen=True)
class Move(Action):
    target: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class SetState(Action):
    key: str = ""
    value: Any = None


@dataclass(frozen=True)
class Silent(Action):
    pass


@dataclass(frozen=True)
class Composite(Action):
    actions: tuple[Action, ...] = ()


# ── LoopState ──────────────────────────────────────────────────────────


@dataclass
class LoopState:
    """Mutable state that the Runtime maintains across ticks."""

    tick: int = 0
    action_log: list[tuple[str, Action]] = field(default_factory=list)
    tick_boundaries: list[int] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def actions_for_tick(self, tick: int) -> list[tuple[str, Action]]:
        if tick < 0 or tick > len(self.tick_boundaries):
            return []
        start = self.tick_boundaries[tick - 1] if tick > 0 else 0
        end = self.tick_boundaries[tick] if tick < len(self.tick_boundaries) else len(self.action_log)
        return self.action_log[start:end]

    def last_tick_actions(self) -> list[tuple[str, Action]]:
        if self.tick == 0:
            return []
        return self.actions_for_tick(self.tick - 1)


# ── RuntimeResult ──────────────────────────────────────────────────────


@dataclass
class RuntimeResult:
    """What ``Runtime.run()`` returns after the loop ends."""

    actions: list[tuple[str, Action]] = field(default_factory=list)
    final_state: LoopState = field(default_factory=LoopState)
    ticks: int = 0

    @property
    def last_speech(self) -> str | None:
        for entity_id, action in reversed(self.actions):
            if isinstance(action, Speak):
                return action.content
        return None

    def speeches(self) -> list[tuple[str, str]]:
        return [
            (eid, a.content) for eid, a in self.actions if isinstance(a, Speak)
        ]

    def __str__(self) -> str:
        return self.last_speech or ""


# ── ChatMessage ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChatMessage:
    """Lightweight message for conversation worlds."""

    sender: str
    content: str
    to: str | frozenset[str] | Literal["*"] = "*"
    channel: str = "default"
