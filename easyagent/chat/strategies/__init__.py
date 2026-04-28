"""Strategy protocols and built-in implementations for Orchestrator.

The Orchestrator (Step 5) is the only place these strategies are
exercised; users compose strategies declaratively to build presets
(``sequential`` / ``debate`` / ``chatroom``) or custom flows.

Four orthogonal axes:

    Routing        — Q3: who hears each message?
    TurnTaking     — Q2: who speaks next?
    StopCondition  — Q4: when do we end?
    Summarize      — Q6: what does the container say to its caller?

Each axis is a ``Protocol``. Built-ins live in submodules to keep
imports flat at the package level — see the per-module docstrings
for which strategy fits which use-case.
"""

from __future__ import annotations

from easyagent.chat.strategies.routing import (
    Broadcast,
    Direct,
    Pipeline,
    Routing,
)
from easyagent.chat.strategies.stop import (
    AfterAllSpoken,
    AllOf,
    AnyOf,
    Idle,
    MaxRounds,
    OnPredicate,
    OnSharedKey,
    StopCondition,
)
from easyagent.chat.strategies.summarize import (
    Aggregate,
    ByJudge,
    Custom,
    FromSharedState,
    LastMessage,
    Summarize,
)
from easyagent.chat.strategies.turn_taking import (
    Conducted,
    Manual,
    Random,
    Reactive,
    RoundRobin,
    Selected,
    TurnTaking,
    Weighted,
)


__all__ = [
    # Protocols
    "Routing",
    "TurnTaking",
    "StopCondition",
    "Summarize",
    # Routing
    "Broadcast",
    "Direct",
    "Pipeline",
    # TurnTaking
    "Conducted",
    "Manual",
    "Random",
    "Reactive",
    "RoundRobin",
    "Selected",
    "Weighted",
    # StopCondition
    "AfterAllSpoken",
    "AllOf",
    "AnyOf",
    "Idle",
    "MaxRounds",
    "OnPredicate",
    "OnSharedKey",
    # Summarize
    "Aggregate",
    "ByJudge",
    "Custom",
    "FromSharedState",
    "LastMessage",
]
