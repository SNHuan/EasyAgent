"""TurnTaking strategies — Q2: who speaks next?

The four legitimate decision modes (P3 in the design doc) are first-
class equals, not "main mode + patches":

    Conducted   — caller dictates the order (used by `sequential`).
    Reactive    — whoever the last message addresses speaks next
                  (the natural mode for `chatroom`/`groupchat`).
    Scheduled   — algorithmic: RoundRobin, Random, Weighted.
    Selected    — a third-party Talker (a "moderator" or "router")
                  picks the next speaker.
    Manual      — Orchestrator does not auto-loop; the user calls
                  members directly inside a `with` block.

Returning ``None`` from ``next`` ends the turn loop just as cleanly
as a stop condition firing. Strategies use this to express "I have
no more turns to schedule" without forcing a separate stop policy.

Design refs: ``docs/chat_layer_design.md`` §6.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from easyagent.chat.talker import Talker
    from easyagent.chat.turn_context import TurnContext


__all__ = [
    "TurnTaking",
    "Conducted",
    "Manual",
    "Random",
    "Reactive",
    "RoundRobin",
    "Selected",
    "Weighted",
]


@runtime_checkable
class TurnTaking(Protocol):
    async def next(self, ctx: "TurnContext") -> str | None:
        """Name of the member that should speak next, or ``None`` to end
        the turn loop.

        Async because some strategies (``Selected``) call out to another
        Talker; most are synchronous and can ``return`` directly from
        an ``async def``.
        """
        ...


# ── Conducted: caller dictates the order ────────────────────────────────


@dataclass
class Conducted:
    """Replay a fixed speaker sequence. After the last name, returns
    ``None`` so the Orchestrator stops.

    Used by ``sequential([a, b, c])``: ``order=["a","b","c"]``. The
    caller controls turn order entirely; speakers do not influence it.
    """

    order: list[str]

    async def next(self, ctx: "TurnContext") -> str | None:
        if ctx.round_index >= len(self.order):
            return None
        return self.order[ctx.round_index]


# ── Manual: don't auto-loop at all ──────────────────────────────────────


@dataclass
class Manual:
    """Returns ``None`` immediately — Orchestrator does no auto-loop.

    The user invokes members themselves inside a ``with`` block (the
    ``chatroom`` preset). Routing still happens, but turn taking is
    fully external.
    """

    async def next(self, ctx: "TurnContext") -> str | None:  # noqa: ARG002
        return None


# ── Reactive: who was just addressed? ───────────────────────────────────


@dataclass
class Reactive:
    """Whoever was last addressed speaks next.

    Reads ``ctx.last_message.to``:

      - ``"*"`` (broadcast): falls back to ``fallback`` (default:
        round-robin among non-sender members).
      - single recipient or subgroup: picks the first matching member
        in registration order.

    If ``ctx.history`` is empty (we haven't even seeded yet), returns
    ``None``. The seed itself is supposed to come in via
    ``Orchestrator.__call__(msg)`` and therefore populates history
    before turn-taking is consulted.
    """

    fallback: "TurnTaking | None" = None

    async def next(self, ctx: "TurnContext") -> str | None:
        last = ctx.last_message
        if last is None:
            return None
        sender = last.sender.name
        if last.is_broadcast:
            fallback = self.fallback or RoundRobin(order=list(ctx.members.keys()))
            return await fallback.next(ctx)
        # Directed: pick the first listed addressee that exists in the
        # current member set and isn't the sender themselves.
        assert isinstance(last.to, frozenset)
        for name in ctx.members:
            if name == sender:
                continue
            if name in last.to:
                return name
        return None


# ── Scheduled: algorithmic turn-taking ──────────────────────────────────


@dataclass
class RoundRobin:
    """Cycle through members in a fixed order, round after round.

    ``order`` defaults to the live member-list order on first call.
    Caching the order matters: a pure ``list(ctx.members)`` would
    re-evaluate insertion order each turn, which is fine for dict
    insertion order in CPython but feels fragile.
    """

    order: list[str] = field(default_factory=list)

    async def next(self, ctx: "TurnContext") -> str | None:
        order = self.order or list(ctx.members.keys())
        if not order:
            return None
        # Skip names that have been removed from the live member set.
        live = [n for n in order if n in ctx.members]
        if not live:
            return None
        return live[ctx.round_index % len(live)]


@dataclass
class Random:
    """Pick a uniformly random member each turn.

    ``avoid_immediate_repeat`` (default True) prevents the same member
    from being chosen twice in a row, which is the realistic-feeling
    default for social-simulation flavor.
    """

    avoid_immediate_repeat: bool = True
    rng: "random.Random | None" = None

    async def next(self, ctx: "TurnContext") -> str | None:
        rng = self.rng or random
        names = list(ctx.members.keys())
        if not names:
            return None
        if self.avoid_immediate_repeat and ctx.last_message is not None:
            last_speaker = ctx.last_message.sender.name
            candidates = [n for n in names if n != last_speaker]
            if candidates:
                names = candidates
        return rng.choice(names)


@dataclass
class Weighted:
    """Sample a member by weights. Weights default to 1.0; missing
    names get the default. Useful for biased simulation (one agent
    talks twice as often as another).
    """

    weights: dict[str, float] = field(default_factory=dict)
    rng: "random.Random | None" = None

    async def next(self, ctx: "TurnContext") -> str | None:
        rng = self.rng or random
        names = list(ctx.members.keys())
        if not names:
            return None
        ws = [max(0.0, self.weights.get(n, 1.0)) for n in names]
        if sum(ws) == 0:
            return None
        return rng.choices(names, weights=ws, k=1)[0]


# ── Selected: ask another Talker ────────────────────────────────────────


@dataclass
class Selected:
    """Delegate the choice to a judge/router Talker.

    The judge is *not* a member — it's an external advisor. On each
    turn, the strategy asks ``judge`` for a reply; the strategy then
    extracts a name from the reply (via ``parse``, default: strip + match
    against ``ctx.members``). If ``judge`` returns silence or names
    something unknown, returns ``None`` to end the loop.

    Common pattern: ``Selected(judge=ModeratorTalker(...))`` for
    "moderator picks who speaks next".
    """

    judge: "Talker"
    parse: "Callable[[str, dict[str, Talker]], str | None] | None" = None

    async def next(self, ctx: "TurnContext") -> str | None:
        from easyagent.chat.message import ChatMessage

        # Build a synthetic prompt summarising the conversation so far,
        # then ask the judge to name the next speaker. We construct the
        # message from the judge's POV so its own MultiAgentFormatter
        # works correctly.
        roster = ", ".join(ctx.members.keys()) or "(none)"
        last = ctx.last_message
        prompt_text = (
            f"Members: {roster}.\n"
            f"Conversation length: {len(ctx.history)} message(s).\n"
            + (f"Last speaker: {last.sender.name}.\n" if last else "")
            + "Which member should speak next? Reply with the name only, "
            "or 'stop' to end the conversation."
        )
        prompt = ChatMessage(
            sender=self.judge.identity,  # judge talks to itself; see _absorb skip
            content=prompt_text,
            channel=ctx.channel,
            role="user",
        )
        # ``judge.observe`` would just stash this in memory and produce
        # nothing, so we call ``__call__`` and read the reply.
        reply = await self.judge(prompt, channel=ctx.channel)
        if reply is None:
            return None
        return self._extract_name(reply.text, ctx.members)

    def _extract_name(self, text: str, members: "dict[str, Talker]") -> str | None:
        if self.parse is not None:
            return self.parse(text, members)
        # Default heuristic: strip whitespace/punctuation, lowercase
        # match against member names. "stop" / "end" / "" → None.
        cleaned = text.strip().strip(".!,;:'\"").lower()
        if not cleaned or cleaned in ("stop", "end", "none"):
            return None
        for name in members:
            if name.lower() == cleaned:
                return name
        # Allow "name says ..." style: take the first word.
        first = cleaned.split()[0] if cleaned.split() else ""
        for name in members:
            if name.lower() == first:
                return name
        return None
