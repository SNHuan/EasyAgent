"""Entity protocol — Q1: who acts?

An Entity has an identity and can act on a Perception to produce an
Action. The protocol is intentionally minimal: everything domain-
specific (LLM calls, tools, spatial movement) lives in implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from easyagent.core.types import Action, Perception
    from easyagent.events.bus import EventBus

__all__ = ["Entity", "RuntimeBindable"]


@runtime_checkable
class Entity(Protocol):
    @property
    def id(self) -> str: ...

    async def act(self, perception: Perception) -> Action | None: ...


@runtime_checkable
class RuntimeBindable(Protocol):
    """Optional internal Interface for entities that consume run context."""

    def bind_runtime_context(
        self,
        *,
        run_id: str,
        run_title: str,
        world: dict[str, object],
        entity: dict[str, object],
        bus: EventBus | None,
    ) -> None: ...
