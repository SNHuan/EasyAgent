"""Turn context — read-only snapshot passed to every strategy.

Strategies (Routing / TurnTaking / StopCondition / Summarize) need to
inspect the conversation's running state to make decisions, but they
must not mutate it. ``TurnContext`` is the immutable-by-convention
view they receive; the Orchestrator is the only thing that writes to
it.

This lives in its own file (rather than under ``strategies/``)
because both the Orchestrator and every strategy module imports it,
and Python doesn't love circular imports under ``strategies/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from easyagent.chat.message import ChatMessage
    from easyagent.chat.shared_state import SharedState
    from easyagent.chat.talker import Talker
    from easyagent.events.bus import EventBus


__all__ = ["TurnContext"]


@dataclass
class TurnContext:
    """Snapshot of the conversation passed into every strategy call.

    Fields:
        members:      Talkers participating, keyed by name.
        channel:      The channel this Orchestrator is driving.
        history:      All ChatMessages emitted so far (seed + replies).
        round_index:  Number of speaker-selection rounds completed.
        idle_rounds:  Consecutive rounds where the chosen speaker
                      returned ``None`` (silent). Drives idle-based
                      stopping conditions.
        bus:          Optional observability bus (None if disabled).
        shared:       Optional shared-state blackboard (None if not
                      configured by the Orchestrator).
        metadata:     Free-form bag for strategies that need to stash
                      cross-call data (e.g. ``Selected`` caching the
                      last judge verdict).
    """

    members: "dict[str, Talker]"
    channel: str
    history: "list[ChatMessage]"
    round_index: int = 0
    idle_rounds: int = 0
    bus: "EventBus | None" = None
    shared: "SharedState | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def last_message(self) -> "ChatMessage | None":
        return self.history[-1] if self.history else None

    def messages_by_sender(self, name: str) -> "list[ChatMessage]":
        return [m for m in self.history if m.sender.name == name]
