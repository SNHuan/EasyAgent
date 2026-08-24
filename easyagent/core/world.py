"""World protocol — the environment entities perceive and act upon.

A World owns state. ``observe`` builds a Perception for one entity;
``apply`` processes an Action back into the state. ``seed`` injects
an external stimulus (typically the user's prompt) before the loop
starts.

World methods are synchronous by design: they are pure state
operations with no I/O. Async belongs in Entity.act, not here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from easyagent.core.types import Action, Perception

__all__ = ["World", "TickAwareWorld", "AdvancingWorld", "TraceableWorld"]


@runtime_checkable
class World(Protocol):
    def observe(self, entity_id: str) -> Perception: ...

    def apply(self, entity_id: str, action: Action) -> None: ...

    def seed(self, content: str, *, sender: str = "user") -> None: ...


@runtime_checkable
class TickAwareWorld(Protocol):
    """Optional internal Interface for worlds that expose the runtime tick."""

    def set_tick(self, tick: int) -> None: ...


@runtime_checkable
class AdvancingWorld(Protocol):
    """Optional internal Interface for worlds with per-tick dynamics."""

    def advance(self, tick: int) -> None: ...


@runtime_checkable
class TraceableWorld(Protocol):
    """Optional internal Interface for custom trace descriptions."""

    def trace_summary(self) -> dict[str, object]: ...
