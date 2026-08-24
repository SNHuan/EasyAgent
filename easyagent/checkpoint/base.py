from __future__ import annotations

from typing import Protocol

from easyagent.checkpoint.schema import AgentCheckpoint


class CheckpointStore(Protocol):
    """Persistence boundary for the latest safe state of an agent session."""

    async def save(self, checkpoint: AgentCheckpoint) -> None:
        ...

    async def load(self, session_id: str) -> AgentCheckpoint | None:
        ...
