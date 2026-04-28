"""Schedule protocol and built-in implementations.

A Schedule answers "who acts next?" by inspecting the LoopState and
returning a list of entity IDs (parallel within one tick) or None to
end the loop.

Wrappers (MaxTicks, UntilIdle, UntilPredicate) compose with any inner
Schedule to add termination conditions.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from easyagent.core.types import LoopState

__all__ = [
    "Schedule",
    "TakeTurns",
    "AllParallel",
    "RoundRobin",
    "RandomOrder",
    "Reactive",
    "MaxTicks",
    "UntilIdle",
    "UntilPredicate",
]


@runtime_checkable
class Schedule(Protocol):
    def next(self, state: LoopState) -> list[str] | None:
        """Return entity IDs to activate this tick, or None to end."""
        ...


# ── Fixed-order schedules ──────────────────────────────────────────────


@dataclass
class TakeTurns:
    """Each entity speaks once in order, then the loop ends."""

    order: list[str] = field(default_factory=list)

    def next(self, state: "LoopState") -> list[str] | None:
        if state.tick >= len(self.order):
            return None
        return [self.order[state.tick]]


@dataclass
class AllParallel:
    """Every entity acts on every tick."""

    ids: list[str] = field(default_factory=list)

    def next(self, state: "LoopState") -> list[str] | None:
        return list(self.ids) if self.ids else None


@dataclass
class RoundRobin:
    """Cycle through entities one per tick, indefinitely."""

    ids: list[str] = field(default_factory=list)

    def next(self, state: "LoopState") -> list[str] | None:
        if not self.ids:
            return None
        return [self.ids[state.tick % len(self.ids)]]


@dataclass
class RandomOrder:
    """Pick one entity at random each tick."""

    ids: list[str] = field(default_factory=list)
    avoid_repeat: bool = True
    rng: "_random.Random | None" = None

    def next(self, state: "LoopState") -> list[str] | None:
        if not self.ids:
            return None
        rng = self.rng or _random
        candidates = list(self.ids)
        if self.avoid_repeat and state.action_log:
            last_id = state.action_log[-1][0]
            filtered = [i for i in candidates if i != last_id]
            if filtered:
                candidates = filtered
        return [rng.choice(candidates)]


@dataclass
class Reactive:
    """The entity addressed by the last Speak action speaks next.

    Falls back to round-robin on broadcasts or when no last action.
    """

    ids: list[str] = field(default_factory=list)

    def next(self, state: "LoopState") -> list[str] | None:
        from easyagent.core.types import Speak

        if not self.ids:
            return None
        if state.action_log:
            _, last_action = state.action_log[-1]
            if isinstance(last_action, Speak) and last_action.to != "*":
                if isinstance(last_action.to, str):
                    targets = [last_action.to]
                else:
                    targets = list(last_action.to)
                for t in targets:
                    if t in self.ids:
                        return [t]
        # Fallback: round-robin
        return [self.ids[state.tick % len(self.ids)]]


# ── Termination wrappers ───────────────────────────────────────────────


@dataclass
class MaxTicks:
    """Wrap any schedule; stop after ``n`` ticks."""

    inner: Schedule
    n: int = 10

    def next(self, state: "LoopState") -> list[str] | None:
        if state.tick >= self.n:
            return None
        return self.inner.next(state)


@dataclass
class UntilIdle:
    """Wrap any schedule; stop after ``grace`` consecutive silent ticks."""

    inner: Schedule
    grace: int = 1

    def next(self, state: "LoopState") -> list[str] | None:
        from easyagent.core.types import Silent

        if state.tick > 0:
            consecutive_silent = 0
            for tick in range(state.tick - 1, -1, -1):
                tick_actions = state.actions_for_tick(tick)
                if all(isinstance(a, Silent) for _, a in tick_actions):
                    consecutive_silent += 1
                else:
                    break
            if consecutive_silent >= self.grace:
                return None
        return self.inner.next(state)


@dataclass
class UntilPredicate:
    """Wrap any schedule; stop when ``predicate(state)`` is True."""

    inner: Schedule
    predicate: Callable[["LoopState"], bool] = field(default=lambda _: False)

    def next(self, state: "LoopState") -> list[str] | None:
        if state.tick > 0 and self.predicate(state):
            return None
        return self.inner.next(state)
