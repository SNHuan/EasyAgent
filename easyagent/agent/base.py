from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from easyagent.agent.session import AgentRunResult, AgentSession, LoopStepResult


class BaseAgent(ABC):
    """Minimal contract for anything a Runtime can host."""

    session_class: type[AgentSession] = None  # type: ignore[assignment]

    @abstractmethod
    async def run(self, user_input: Any, *, session: "AgentSession | None" = None) -> "AgentRunResult": ...

    def create_session(self) -> "AgentSession":
        from easyagent.agent.session import AgentSession

        return (self.session_class or AgentSession)()

    async def on_session_start(self, session: "AgentSession") -> None: ...
    async def on_session_end(self, session: "AgentSession") -> None: ...

    async def run_session(self, session: "AgentSession", user_input: Any) -> str:
        raise NotImplementedError

    async def step(self, session: "AgentSession") -> "LoopStepResult":
        raise NotImplementedError
