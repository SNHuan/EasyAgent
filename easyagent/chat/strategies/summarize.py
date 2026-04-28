"""Summarize strategies — Q6: what does the container say to its
caller?

The Orchestrator's killer feature is being itself a Talker — but
that requires it to produce a ``ChatMessage`` after the turn loop
ends. ``Summarize`` decides what that message is. This is the
boundary between "internal sub-conversation" and "what the outside
world sees".

Five built-ins:

  LastMessage      — the most recent non-silent reply (default).
  Aggregate        — concatenate all replies, optionally filtered.
  ByJudge          — invoke a Talker (judge/aggregator) to produce
                     a summary. Crucial for nested debate flows.
  FromSharedState  — return whatever lives at a given key on the
                     blackboard. For workshop/blackboard patterns.
  Custom           — arbitrary async callable.

Returning ``None`` from ``produce`` means "the container has nothing
to say"; legal but unusual.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from easyagent.chat.message import ChatMessage, Identity
    from easyagent.chat.talker import Talker
    from easyagent.chat.turn_context import TurnContext


__all__ = [
    "Summarize",
    "Aggregate",
    "ByJudge",
    "Custom",
    "FromSharedState",
    "LastMessage",
]


@runtime_checkable
class Summarize(Protocol):
    async def produce(
        self,
        ctx: "TurnContext",
        container: "Identity",
    ) -> "ChatMessage | None":
        """Build the message the Orchestrator returns to its caller.

        ``container`` is the Orchestrator's own identity — strategies
        use it as the ``sender`` of the produced message so callers see
        "the orchestrator said X" rather than "alice said X".
        """
        ...


# ── LastMessage ─────────────────────────────────────────────────────────


@dataclass
class LastMessage:
    """Return the last non-silent message verbatim, but rebadged as
    coming from the container.

    The natural default for most flows: the orchestrator's "answer" is
    whatever its members converged on at the very end. Re-badging the
    sender is what makes nested flows clean — the outer pipeline sees
    a message from ``debate_team``, not from ``alice``.
    """

    include_seed: bool = False
    """When True, the original seed (caller's prompt) is treated as a
    candidate for "last message" — only relevant if no member ever
    spoke. Defaults to False so an empty turn loop returns ``None``."""

    async def produce(
        self,
        ctx: "TurnContext",
        container: "Identity",
    ) -> "ChatMessage | None":
        from easyagent.chat.message import ChatMessage

        for m in reversed(ctx.history):
            if not self.include_seed and m.sender.name not in ctx.members:
                # Seed messages come from outside the orchestrator's
                # member set; skip them by default.
                continue
            return ChatMessage(
                sender=container,
                content=m.content,
                to="*",
                channel=ctx.channel,
                role="assistant",
                reply_to=m.id,
                metadata={**m.metadata, "underlying_sender": m.sender.name},
            )
        return None


# ── Aggregate ───────────────────────────────────────────────────────────


@dataclass
class Aggregate:
    """Concatenate every reply (optionally filtered) into one message.

    Useful when the orchestrator's "answer" is a transcript: every
    member's contribution is preserved, prefixed with their name. Used
    by the ``fanout`` preset to gather parallel opinions.
    """

    only: list[str] | None = None
    separator: str = "\n\n"

    async def produce(
        self,
        ctx: "TurnContext",
        container: "Identity",
    ) -> "ChatMessage | None":
        from easyagent.chat.message import ChatMessage

        keep = self.only or list(ctx.members.keys())
        parts: list[str] = []
        for m in ctx.history:
            if m.sender.name not in keep:
                continue
            parts.append(f"{m.sender.name}: {m.text}")
        if not parts:
            return None
        return ChatMessage(
            sender=container,
            content=self.separator.join(parts),
            to="*",
            channel=ctx.channel,
            role="assistant",
        )


# ── ByJudge ─────────────────────────────────────────────────────────────


@dataclass
class ByJudge:
    """Ask a Talker to summarise the conversation.

    The judge is invoked with a prompt that lays out the transcript;
    its reply becomes the orchestrator's outbound message. Critical
    for nested-flow correctness: a debate orchestrator wrapped inside
    ``sequential([planner, debate_team, writer])`` should not leak
    alice/bob's argument back-and-forth into the writer's input — it
    should hand the writer a single distilled verdict, which is what
    ByJudge produces.

    The judge typically lives outside ``ctx.members`` (otherwise it
    would also be participating in the debate). Pass it directly to
    the strategy.
    """

    judge: "Talker"
    instruction: str = (
        "You are summarising the conversation above. Produce a single, "
        "concise message capturing the conclusion. Do not list individual "
        "speakers' contributions — just the resolved answer."
    )

    async def produce(
        self,
        ctx: "TurnContext",
        container: "Identity",
    ) -> "ChatMessage | None":
        from easyagent.chat.message import ChatMessage

        if not ctx.history:
            return None
        # Render the transcript so the judge sees who said what.
        transcript = "\n".join(
            f"{m.sender.name}: {m.text}"
            for m in ctx.history
            if m.sender.name in ctx.members
        )
        prompt = ChatMessage(
            sender=container,  # judge sees container as the prompter
            content=f"Transcript:\n{transcript}\n\n{self.instruction}",
            to=self.judge.identity.name,
            channel=ctx.channel,
            role="user",
        )
        reply = await self.judge(prompt, channel=ctx.channel)
        if reply is None:
            return None
        # Rebadge as coming from the container so callers don't see
        # the judge's identity bleed through.
        return ChatMessage(
            sender=container,
            content=reply.content,
            to="*",
            channel=ctx.channel,
            role="assistant",
            reply_to=reply.id,
            metadata={**reply.metadata, "judged_by": self.judge.identity.name},
        )


# ── FromSharedState ─────────────────────────────────────────────────────


@dataclass
class FromSharedState:
    """Pull the answer out of the blackboard at ``key``.

    The pattern: members collaborate by writing artifacts to
    ``SharedState`` rather than chatting; the orchestrator's exit
    value is just the final artifact. If the key is missing, returns
    ``None`` (the orchestrator yields nothing).
    """

    key: str

    async def produce(
        self,
        ctx: "TurnContext",
        container: "Identity",
    ) -> "ChatMessage | None":
        from easyagent.chat.message import ChatMessage

        if ctx.shared is None or not ctx.shared.has(self.key):
            return None
        value = ctx.shared.get(self.key)
        return ChatMessage(
            sender=container,
            content=str(value),
            to="*",
            channel=ctx.channel,
            role="assistant",
            metadata={"shared_key": self.key},
        )


# ── Custom ──────────────────────────────────────────────────────────────


@dataclass
class Custom:
    """Arbitrary async callable. Last resort when no built-in fits.

    The callable is responsible for honoring sender/channel/role
    conventions; nothing wraps its output.
    """

    fn: Callable[["TurnContext", "Identity"], "Awaitable[ChatMessage | None]"]

    async def produce(
        self,
        ctx: "TurnContext",
        container: "Identity",
    ) -> "ChatMessage | None":
        return await self.fn(ctx, container)
