from __future__ import annotations

from typing import Any

from easyagent.agent.base import BaseAgent
from easyagent.agent.session import AgentSession
from easyagent.loop.base import BaseLoop
from easyagent.model.schema import Message


class SingleTurnLoop(BaseLoop):
    async def run(self, agent: BaseAgent, session: AgentSession, user_input: Any) -> str:
        session.add_message(Message.user(user_input))
        messages = await session.get_model_messages(agent.system_prompt)
        response = await session.current_model.call_with_history(messages)
        session.add_message(Message.from_response(response))
        session.final_output = response.content
        return response.content
