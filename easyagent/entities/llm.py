"""LLMEntity — wraps an Agent as an Entity.

The key design decision: memory is rebuilt from Perception each turn
(not incrementally appended). This eliminates the double-write problem
that plagued the old LLMTalker. The agent's memory is cleared and
reconstructed from the MessagesSlice so the LLM sees exactly what the
World says it should see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easyagent.core.types import Action, MessagesSlice, Perception, Speak

if TYPE_CHECKING:
    from easyagent.agent.agent import Agent
    from easyagent.agent.session import AgentSession
    from easyagent.context.base import BaseContext
    from easyagent.events.bus import EventBus

__all__ = ["LLMEntity"]


class LLMEntity:
    """Adapter: single-agent ``Agent`` → multi-agent ``Entity``."""

    def __init__(
        self,
        entity_id: str,
        agent: Agent,
        *,
        formatter: BaseContext | None = None,
    ) -> None:
        self._id = entity_id
        self._agent = agent
        self._formatter = formatter
        self._session: AgentSession | None = None
        self._runtime_trace_context: dict[str, Any] = {}
        self._runtime_bus: EventBus | None = None

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> Action | None:
        from easyagent.model.schema import Message

        session = self._ensure_session()

        msg_slice = perception.of_type(MessagesSlice)
        if msg_slice is None or not msg_slice.messages:
            return None

        # 1. Clear memory — rebuild from scratch each turn
        assert session.memory is not None
        session.memory.clear()

        # 2. Rebuild the complete conversation in its original order.
        if all(message.sender == self._id for message in msg_slice.messages):
            return None

        for chat_msg in msg_slice.messages:
            if chat_msg.sender == self._id:
                session.memory.add(
                    Message.assistant(chat_msg.content, name=self._id)
                )
            else:
                session.memory.add(
                    Message.user(chat_msg.content, name=chat_msg.sender)
                )

        # 3. Drive the complete lifecycle without appending a duplicate input.
        output = await session.run_prepared()
        if not output.strip():
            return None

        return Speak(content=output)

    def bind_runtime_context(
        self,
        *,
        run_id: str,
        run_title: str,
        world: dict[str, object],
        entity: dict[str, object],
        bus: "EventBus | None",
    ) -> None:
        self._runtime_bus = bus
        self._runtime_trace_context = {
            "run_id": run_id,
            "run_scope": "runtime",
            "run_title": run_title,
            "world": world,
            "entity": entity,
        }
        if self._session is not None:
            self._apply_runtime_trace_context(self._session)

    def _ensure_session(self) -> "AgentSession":
        if self._session is None:
            from easyagent.context.multi_agent import MultiAgentFormatter

            context = self._formatter
            if context is None:
                context = MultiAgentFormatter(self_name=self._id)
            self._session = self._agent.create_session(context=context)
            self._apply_runtime_trace_context(self._session)
        return self._session

    def _apply_runtime_trace_context(self, session: "AgentSession") -> None:
        if self._runtime_bus is not None:
            session.event_bus = self._runtime_bus
        if self._runtime_trace_context:
            session.metadata.update(self._runtime_trace_context)
