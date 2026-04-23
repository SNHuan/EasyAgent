from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from easyagent.agent.session import AgentSession
from easyagent.model.base import BaseLLM


class BaseAgent(ABC):
    def __init__(
        self,
        default_model: BaseLLM,
        system_prompt: str = "",
    ):
        self._default_model = default_model
        self._system_prompt = system_prompt

    @property
    def default_model(self) -> BaseLLM:
        return self._default_model

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @abstractmethod
    def create_session(self, **kwargs: Any) -> AgentSession:
        pass

    @abstractmethod
    async def run(self, user_input: Any, *, session: AgentSession | None = None) -> str:
        pass

    @abstractmethod
    def build_system_prompt(self, session: AgentSession) -> str:
        pass

    @abstractmethod
    def get_tool_schemas(self, session: AgentSession) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def execute_tool_call(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        pass
