"""Chat layer: user-facing multi-agent collaboration API.

This package adds a thin, ergonomic layer on top of EasyAgent's existing
session/runtime core. The chat layer answers six recurring multi-agent
questions:

    Q1 What is the message unit?         → ChatMessage
    Q2 Who decides who speaks next?      → TurnTaking strategy
    Q3 Who decides who hears it?         → Routing strategy
    Q4 When do we stop?                  → StopCondition strategy
    Q5 Where does state live?            → Memory + SharedState
    Q6 Can a sub-system act as a Talker? → Orchestrator implements Talker

Symbols are re-exported here as the package's public surface; users
import from ``easyagent.chat`` rather than reaching into submodules.
"""

from __future__ import annotations

from easyagent.chat.formatter import MultiAgentFormatter
from easyagent.chat.message import BROADCAST, ChatMessage, Identity
from easyagent.chat.orchestrator import ManualSession, Orchestrator
from easyagent.chat.presets import chatroom, debate, fanout, groupchat, sequential
from easyagent.chat.shared_state import SharedState, StateChangedEvent
from easyagent.chat.talker import HumanTalker, LLMTalker, RuntimeTalker, Talker
from easyagent.chat.turn_context import TurnContext

__all__ = [
    "BROADCAST",
    "ChatMessage",
    "HumanTalker",
    "Identity",
    "LLMTalker",
    "ManualSession",
    "MultiAgentFormatter",
    "Orchestrator",
    "RuntimeTalker",
    "SharedState",
    "StateChangedEvent",
    "Talker",
    "TurnContext",
    # Presets
    "chatroom",
    "debate",
    "fanout",
    "groupchat",
    "sequential",
]
