"""Chat layer: user-facing multi-agent collaboration API.

This package adds a thin, ergonomic layer on top of EasyAgent's existing
session/runtime core. See ``docs/chat_layer_design.md`` for the full
design rationale; in short, the chat layer answers six recurring
multi-agent questions:

    Q1 What is the message unit?         → ChatMessage
    Q2 Who decides who speaks next?      → TurnTaking strategy
    Q3 Who decides who hears it?         → Routing strategy
    Q4 When do we stop?                  → StopCondition strategy
    Q5 Where does state live?            → Memory + SharedState
    Q6 Can a sub-system act as a Talker? → Orchestrator implements Talker

Symbols are re-exported here as the package's public surface; users
import from ``easyagent.chat`` rather than reaching into submodules.

Modules are added incrementally — see ``docs/chat_layer_design.md`` §12
for the implementation plan.
"""

from __future__ import annotations

from easyagent.chat.message import BROADCAST, ChatMessage, Identity

__all__ = [
    "BROADCAST",
    "ChatMessage",
    "Identity",
]
