from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from easyagent.events.base import BaseEvent
from easyagent.events.types import AgentId


@dataclass
class RuntimeState:
    """Mutable state collected while a runtime is running."""

    agent_ids: list[AgentId] = field(default_factory=list)
    events: list[BaseEvent] = field(default_factory=list)
    stop_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tick: int = 0
    idle_steps: int = 0
    max_ticks: int | None = None
