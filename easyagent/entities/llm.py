"""LLMEntity — wraps an Agent as an Entity.

The key design decision: memory is rebuilt from Perception each turn
(not incrementally appended). This eliminates the double-write problem
that plagued the old LLMTalker. The agent's memory is cleared and
reconstructed from the MessagesSlice so the LLM sees exactly what the
World says it should see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyagent.core.types import Action, MessagesSlice, Perception, Speak

if TYPE_CHECKING:
    from easyagent.agent.agent import Agent
    from easyagent.agent.session import AgentSession
    from easyagent.context.base import BaseContext

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

        # 2. Rebuild conversation from perception
        last_content = ""
        for chat_msg in msg_slice.messages:
            if chat_msg.sender == self._id:
                session.memory.add(
                    Message.assistant(chat_msg.content, name=self._id)
                )
            else:
                session.memory.add(
                    Message.user(chat_msg.content, name=chat_msg.sender)
                )
                last_content = chat_msg.content

        if not last_content:
            return None

        # 3. Drive the agent's step loop
        session.iteration_count = 0
        session.loop_steps.clear()
        session.loop_state.clear()

        from easyagent.agent.session import LoopStepResult

        result: LoopStepResult = await self._agent.step(session)
        session.loop_steps.append(result)
        while not result.done:
            result = await self._agent.step(session)
            session.loop_steps.append(result)

        output = result.output or session.final_output or ""
        if not output.strip():
            return None

        return Speak(content=output)

    def _ensure_session(self) -> "AgentSession":
        if self._session is None:
            from easyagent.context.multi_agent import MultiAgentFormatter

            context = self._formatter
            if context is None:
                context = MultiAgentFormatter(self_name=self._id)
            self._session = self._agent.create_session(context=context)
        return self._session
