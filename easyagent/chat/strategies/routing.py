"""Routing strategies — Q3: who hears each message?

A ``Routing`` strategy is a pure function from ``(message, context)`` to
the list of member names that should ``observe`` the message. The
Orchestrator never broadcasts blindly; it always asks the routing
strategy which members are addressees.

Three built-ins:

  Broadcast — every member except the sender gets every message.
              The default for group-chat / debate scenarios.

  Direct    — honour ``msg.to``: a single recipient or subgroup.
              Matches the ``ChatMessage.to`` field. Senders never
              receive their own messages.

  Pipeline  — strict linear hand-off: message travels to the next
              member in a fixed order. Used by the ``sequential``
              preset to enforce deterministic A → B → C flow.

Custom routing is rare. If you need it, implement the protocol and
plug it into ``Orchestrator(routing=...)``.

Design refs: ``docs/chat_layer_design.md`` §6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from easyagent.chat.message import ChatMessage
    from easyagent.chat.turn_context import TurnContext


__all__ = ["Routing", "Broadcast", "Direct", "Pipeline"]


@runtime_checkable
class Routing(Protocol):
    def targets(
        self,
        msg: "ChatMessage",
        ctx: "TurnContext | None",
    ) -> list[str]:
        """Names of members that should ``observe`` ``msg``. The sender
        is excluded by convention even if technically eligible — the
        Orchestrator does not double-check, so the strategy must.

        ``ctx`` is ``None`` only when called from outside a turn loop
        (e.g. ``Orchestrator.observe`` forwarding an external message
        before any turn has run). Strategies that depend on ``ctx``
        should handle ``None`` gracefully.
        """
        ...


@dataclass
class Broadcast:
    """Send every message to every member except the sender."""

    def targets(
        self,
        msg: "ChatMessage",
        ctx: "TurnContext | None",
    ) -> list[str]:
        if ctx is None:
            # No context yet — addressee list comes purely from the
            # message itself. Caller (Orchestrator) supplies members
            # directly when needed.
            return []
        return [name for name in ctx.members if name != msg.sender.name]


@dataclass
class Direct:
    """Honour ``msg.to`` literally.

    ``msg.to == "*"`` falls back to broadcast semantics; otherwise the
    message goes only to the listed recipients (intersected with the
    actual member set). Useful when talkers themselves decide who to
    address — the prototypical "groupchat with @-mentions" mode.
    """

    def targets(
        self,
        msg: "ChatMessage",
        ctx: "TurnContext | None",
    ) -> list[str]:
        if ctx is None:
            return []
        if msg.is_broadcast:
            return [name for name in ctx.members if name != msg.sender.name]
        # Static type narrowing: by ChatMessage.__post_init__ a non-
        # broadcast ``to`` is always a frozenset.
        assert isinstance(msg.to, frozenset)
        return [
            name
            for name in msg.to
            if name in ctx.members and name != msg.sender.name
        ]


@dataclass
class Pipeline:
    """Strict linear hand-off: A → B → C → ...

    The first message (the seed from outside) goes to the first
    member in ``order``. Each subsequent message — in practice the
    reply produced by the last speaker — is routed to the *next*
    member in ``order``. After the last member there is nowhere
    to forward to; the Orchestrator's stop condition is responsible
    for terminating the loop at that point (typically
    ``AfterAllSpoken``).

    Used by the ``sequential`` preset.
    """

    order: list[str]

    def targets(
        self,
        msg: "ChatMessage",
        ctx: "TurnContext | None",
    ) -> list[str]:
        if not self.order:
            return []
        sender = msg.sender.name
        if sender not in self.order:
            # External seed — hand to the first member.
            return [self.order[0]]
        idx = self.order.index(sender)
        if idx + 1 >= len(self.order):
            # End of pipeline; nothing more to hand off.
            return []
        return [self.order[idx + 1]]
