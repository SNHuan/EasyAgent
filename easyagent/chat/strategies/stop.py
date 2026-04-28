"""StopCondition strategies — Q4: when do we end?

Stop conditions inspect the (read-only) ``TurnContext`` after each
turn and return ``(stop_now, reason)``. Reasons are surfaced on the
Orchestrator's outbound message metadata for observability.

Built-ins are designed to compose: most real flows want
``AnyOf([MaxRounds(n), Idle(), OnPredicate(...)])`` — fire whichever
hits first.

Design refs: ``docs/chat_layer_design.md`` §6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from easyagent.chat.turn_context import TurnContext


__all__ = [
    "StopCondition",
    "AfterAllSpoken",
    "AllOf",
    "AnyOf",
    "Idle",
    "MaxRounds",
    "OnPredicate",
    "OnSharedKey",
]


@runtime_checkable
class StopCondition(Protocol):
    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        """Return ``(stop, reason)``. ``reason`` is ignored when
        ``stop`` is False but should be human-readable when True."""
        ...


@dataclass
class MaxRounds:
    """Cap turn-loop iterations. ``round_index`` is 0-based, so
    ``MaxRounds(3)`` allows 3 rounds (indices 0, 1, 2) and stops at
    the start of round 3.
    """

    n: int

    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        if ctx.round_index >= self.n:
            return True, f"max_rounds={self.n}"
        return False, ""


@dataclass
class Idle:
    """Stop after ``grace`` consecutive silent turns.

    Silence here means the chosen speaker returned ``None`` (P7).
    Useful for ``groupchat`` flows: keep going as long as someone
    has something to say, stop once everyone passes.
    """

    grace: int = 1

    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        if ctx.idle_rounds > self.grace:
            return True, f"idle_for={ctx.idle_rounds}"
        return False, ""


@dataclass
class AfterAllSpoken:
    """Stop once every named member has produced at least one
    non-silent message. The Orchestrator drives turn order via the
    turn-taking strategy; this just monitors who's been heard from.

    The natural pair for ``Conducted`` (sequential): once we've
    heard from everyone in the order, we're done.
    """

    members: list[str] | None = None

    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        target = self.members if self.members is not None else list(ctx.members.keys())
        if not target:
            return True, "no_members"
        spoken = {m.sender.name for m in ctx.history if m.sender.name in target}
        if spoken >= set(target):
            return True, "all_spoken"
        return False, ""


@dataclass
class OnPredicate:
    """Fire when an arbitrary predicate over ``ctx`` returns True.

    Use this for "conversation is done" signals that don't fit the
    other built-ins:

        OnPredicate(lambda ctx: ctx.last_message
                                and ctx.last_message.metadata.get("done"))

    The predicate is called once per turn after the message has
    been added to history.
    """

    predicate: Callable[["TurnContext"], bool]
    reason: str = "predicate"

    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        try:
            if self.predicate(ctx):
                return True, self.reason
        except Exception as exc:  # noqa: BLE001
            return True, f"predicate_error: {exc!r}"
        return False, ""


@dataclass
class OnSharedKey:
    """Fire when a key in shared state matches a predicate.

    Convenience over ``OnPredicate``: by far the most common reason
    to halt a workshop-style flow is "the artifact we wanted has been
    written to the blackboard".

        OnSharedKey("final_report")        # exists at all
        OnSharedKey("score", lambda v: v >= 0.9)
    """

    key: str
    predicate: Callable[[object], bool] | None = None

    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        if ctx.shared is None or not ctx.shared.has(self.key):
            return False, ""
        if self.predicate is None:
            return True, f"shared:{self.key}"
        try:
            if self.predicate(ctx.shared.get(self.key)):
                return True, f"shared:{self.key}_matched"
        except Exception as exc:  # noqa: BLE001
            return True, f"shared_predicate_error: {exc!r}"
        return False, ""


# ── Composition ─────────────────────────────────────────────────────────


@dataclass
class AnyOf:
    """Stop if any sub-condition fires. Reason is the first match's."""

    conditions: list[StopCondition] = field(default_factory=list)

    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        for cond in self.conditions:
            stop, reason = cond.check(ctx)
            if stop:
                return True, reason
        return False, ""


@dataclass
class AllOf:
    """Stop only if every sub-condition fires (rare; mostly useful
    when expressing 'we're done with phase 1 AND phase 2')."""

    conditions: list[StopCondition] = field(default_factory=list)

    def check(self, ctx: "TurnContext") -> tuple[bool, str]:
        if not self.conditions:
            return False, ""
        reasons = []
        for cond in self.conditions:
            stop, reason = cond.check(ctx)
            if not stop:
                return False, ""
            reasons.append(reason)
        return True, "; ".join(reasons)
