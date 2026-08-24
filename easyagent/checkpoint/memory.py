from __future__ import annotations

import json

from easyagent.checkpoint.schema import AgentCheckpoint


class MemoryCheckpointStore:
    """JSON-compatible in-process checkpoint store."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, str] = {}

    async def save(self, checkpoint: AgentCheckpoint) -> None:
        self._checkpoints[checkpoint.session_id] = json.dumps(
            checkpoint.to_dict()
        )

    async def load(self, session_id: str) -> AgentCheckpoint | None:
        payload = self._checkpoints.get(session_id)
        if payload is None:
            return None
        return AgentCheckpoint.from_dict(json.loads(payload))
