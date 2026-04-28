"""SpatialWorld — 2D grid with range-limited communication.

Entities have positions on a Grid2D. Perception includes a SpatialSlice
(own position + nearby entity IDs) in addition to a MessagesSlice
(only messages from entities within ``listen_radius``).

``apply`` handles both Speak (append message, but only audible within
range) and Move (update position).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from easyagent.core.types import (
    Action,
    ChatMessage,
    MessagesSlice,
    Move,
    Perception,
    PerceptionSlice,
    Speak,
    SpatialSlice,
)

__all__ = ["Grid2D", "SpatialWorld"]


@dataclass
class Grid2D:
    """Position registry for entities on a 2D plane."""

    positions: dict[str, tuple[int, int]] = field(default_factory=dict)

    def place(self, entity_id: str, pos: tuple[int, int]) -> None:
        self.positions[entity_id] = pos

    def move(self, entity_id: str, target: tuple[int, int]) -> None:
        self.positions[entity_id] = target

    def distance(self, a: str, b: str) -> float:
        pa = self.positions.get(a, (0, 0))
        pb = self.positions.get(b, (0, 0))
        return math.sqrt((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2)

    def neighbors_of(self, entity_id: str, radius: float) -> tuple[str, ...]:
        if entity_id not in self.positions:
            return ()
        return tuple(
            eid for eid in self.positions
            if eid != entity_id and self.distance(entity_id, eid) <= radius
        )


@dataclass
class SpatialWorld:
    """2D spatial world with range-limited perception."""

    grid: Grid2D = field(default_factory=Grid2D)
    listen_radius: float = 5.0
    channel: str = "default"
    history: list[ChatMessage] = field(default_factory=list)
    _tick: int = 0

    def observe(self, entity_id: str) -> Perception:
        pos = self.grid.positions.get(entity_id, (0, 0))
        nearby = self.grid.neighbors_of(entity_id, self.listen_radius)
        audible_senders = {entity_id, *nearby, "user"}
        visible = [m for m in self.history if m.sender in audible_senders]

        slices: list[PerceptionSlice] = [
            MessagesSlice(messages=tuple(visible)),
            SpatialSlice(position=pos, nearby=nearby),
        ]
        return Perception(entity_id=entity_id, tick=self._tick, slices=tuple(slices))

    def apply(self, entity_id: str, action: Action) -> None:
        if isinstance(action, Move):
            self.grid.move(entity_id, action.target)
        elif isinstance(action, Speak):
            self.history.append(
                ChatMessage(
                    sender=entity_id,
                    content=action.content,
                    to=action.to,
                    channel=self.channel,
                )
            )

    def seed(self, content: str, *, sender: str = "user") -> None:
        self.history.append(
            ChatMessage(
                sender=sender,
                content=content,
                to="*",
                channel=self.channel,
            )
        )

    def set_tick(self, tick: int) -> None:
        self._tick = tick
