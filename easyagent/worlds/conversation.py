"""ConversationWorld — the most common World: chat messages.

Maintains a flat message history. Every entity sees all messages
(broadcast visibility). ``apply`` converts Speak actions into
ChatMessages appended to history.
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

__all__ = ["ConversationWorld"]


@dataclass
class ConversationWorld:
    """Flat conversation history with broadcast visibility."""

    channel: str = "default"
    history: list[ChatMessage] = field(default_factory=list)
    _tick: int = 0

    def observe(self, entity_id: str) -> Perception:
        slices: list[PerceptionSlice] = [
            MessagesSlice(messages=tuple(self.history)),
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
