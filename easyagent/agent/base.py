from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator

from easyagent.model.schema import Message

if TYPE_CHECKING:
    from easyagent.agent.session import AgentRunResult, AgentSession, LoopStepResult
    from easyagent.events import EventBus


class BaseAgent(ABC):
    """Minimal contract for anything a Runtime can host."""

    session_class: type[AgentSession] = None  # type: ignore[assignment]

    @abstractmethod
    async def run(
        self,
        user_input: Any,
        *,
        session: "AgentSession | None" = None,
        event_bus: "EventBus | None" = None,
    ) -> "AgentRunResult": ...

    async def stream(
        self,
        user_input: Any,
        *,
        session: "AgentSession | None" = None,
        event_bus: "EventBus | None" = None,
    ) -> AsyncIterator[str]:
        ...

    def create_session(self) -> "AgentSession":
        from easyagent.agent.session import AgentSession

        return (self.session_class or AgentSession)()

    async def on_session_start(self, session: "AgentSession") -> None: ...
    async def on_session_end(self, session: "AgentSession") -> None: ...

    async def run_session(self, session: "AgentSession", user_input: Any) -> str:
        raise NotImplementedError

    async def step(self, session: "AgentSession") -> "LoopStepResult":
        raise NotImplementedError

    async def observe(
        self,
        message: Message | str,
        *,
        session: "AgentSession | None" = None,
        sender: str | None = None,
    ) -> None:
        """Absorb a message into the session's memory without triggering a reply.

        This is the Talker-style read-only contract surfaced at the
        BaseAgent level so callers can use a plain agent for the
        "watch the conversation" half of multi-agent without needing
        the chat layer's ``LLMTalker`` wrapper.

        Strings are wrapped as ``Message.user(...)`` (with optional
        ``name=sender`` for multi-agent attribution); already-built
        ``Message`` objects pass through. If no session is provided a
        fresh one is created — practical for single-shot side calls,
        though most users will want to manage their own session and
        pass it explicitly.
        """
        active = session or self.create_session()
        if isinstance(message, str):
            msg = Message.user(message, name=sender)
        else:
            msg = message
        # ``add_message`` lives on AgentSession and writes through to memory.
        active.add_message(msg)
