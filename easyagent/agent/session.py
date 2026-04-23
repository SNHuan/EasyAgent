from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from easyagent.context.base import BaseContext
from easyagent.memory.base import BaseMemory
from easyagent.model.base import BaseLLM
from easyagent.model.schema import Message


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentSession:
    current_model: BaseLLM
    memory: BaseMemory
    context: BaseContext
    enabled_tools: list[str] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.IDLE
    iteration_count: int = 0
    final_output: str | None = None

    def add_message(self, message: Message) -> None:
        self.memory.add(message)

    def get_all_messages(self) -> list[Message]:
        return self.memory.get_all()

    async def get_model_messages(self, system_prompt: str) -> list[dict[str, Any]]:
        return await self.context.build_messages(self.memory, system_prompt)
