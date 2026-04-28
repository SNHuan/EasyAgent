"""PipelineWorld — linear hand-off visibility.

Each entity only sees messages from the previous entity in the pipeline
(plus the original seed). Used by the ``sequential`` preset.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from easyagent.core.types import (
    Action,
    ChatMessage,
    MessagesSlice,
    Perception,
    PerceptionSlice,
    Speak,
)

__all__ = ["PipelineWorld"]


@dataclass
class PipelineWorld:
    """Restricted visibility: entity N sees only seed + entity N-1's output."""

    order: list[str] = field(default_factory=list)
    channel: str = "default"
    history: list[ChatMessage] = field(default_factory=list)
    _tick: int = 0

    def observe(self, entity_id: str) -> Perception:
        if entity_id not in self.order:
            visible = list(self.history)
        else:
            idx = self.order.index(entity_id)
            if idx == 0:
                visible = [m for m in self.history if m.sender not in self.order]
            else:
                prev = self.order[idx - 1]
                visible = [
                    m for m in self.history
                    if m.sender not in self.order or m.sender == prev
                ]
        slices: list[PerceptionSlice] = [
            MessagesSlice(messages=tuple(visible)),
        ]
        return Perception(entity_id=entity_id, tick=self._tick, slices=tuple(slices))

    def apply(self, entity_id: str, action: Action) -> None:
        if isinstance(action, Speak):
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
