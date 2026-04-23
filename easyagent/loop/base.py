from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from easyagent.agent.base import BaseAgent
from easyagent.agent.session import AgentSession


class BaseLoop(ABC):
    @abstractmethod
    async def run(self, agent: BaseAgent, session: AgentSession, user_input: Any) -> str:
        pass
