from __future__ import annotations

import json
from typing import Any

from easyagent.agent.base import BaseAgent
from easyagent.agent.session import AgentSession
from easyagent.config.base import is_debug
from easyagent.debug.log import Color, Logger
from easyagent.loop.base import BaseLoop
from easyagent.model.schema import Message, content_to_text
from easyagent.prompt.react import REACT_END_TOKEN, REACT_SYSTEM_PROMPT


class ReActLoop(BaseLoop):
    def __init__(self, max_iterations: int = 10, end_token: str = REACT_END_TOKEN):
        self._max_iterations = max_iterations
        self._end_token = end_token
        self._log = Logger(self.__class__.__name__)

    async def run(self, agent: BaseAgent, session: AgentSession, user_input: Any) -> str:
        session.add_message(Message.user(user_input))
        if is_debug():
            self._log.debug(f"User: {content_to_text(user_input)}")

        for iteration in range(self._max_iterations):
            session.iteration_count = iteration + 1
            if is_debug():
                self._log.debug(f"Iteration {iteration + 1}/{self._max_iterations}")
            system_prompt = self._build_system_prompt(agent, session)
            messages = await session.get_model_messages(system_prompt)
            tool_schemas = agent.get_tool_schemas(session)
            kwargs: dict[str, Any] = {}
            if tool_schemas:
                kwargs["tools"] = tool_schemas

            response = await session.current_model.call_with_history(messages, **kwargs)
            if is_debug() and response.content:
                self._log.info(f"Assistant: {response.content}", color=Color.GRAY)

            if self._is_finished(response.content):
                final_answer = self._extract_final_answer(response.content)
                session.add_message(Message.assistant(final_answer))
                self._log.info(f"Final: {final_answer}", color=Color.CYAN)
                return final_answer

            if not response.tool_calls:
                session.add_message(Message.from_response(response))
                continue

            session.add_message(
                Message.assistant(response.content, self._format_tool_calls(response.tool_calls))
            )

            for tool_call in response.tool_calls:
                if is_debug():
                    self._log.info(
                        f"Tool call: {tool_call.name}({tool_call.arguments})",
                        color=Color.YELLOW,
                    )
                result = await agent.execute_tool_call(
                    session,
                    tool_call.name,
                    tool_call.arguments,
                )
                if is_debug():
                    self._log.info(f"Tool result: {result}", color=Color.GREEN)
                session.add_message(Message.tool(result, tool_call.id))

        return "Max iterations reached"

    def _build_system_prompt(self, agent: BaseAgent, session: AgentSession) -> str:
        extra_prompt = agent.build_system_prompt(session)
        if extra_prompt:
            return "\n\n".join([REACT_SYSTEM_PROMPT, extra_prompt])
        return REACT_SYSTEM_PROMPT

    def _is_finished(self, content: str) -> bool:
        return self._end_token in content

    def _extract_final_answer(self, content: str) -> str:
        if self._end_token in content:
            return content.split(self._end_token)[0].strip()
        return content

    def _format_tool_calls(self, tool_calls: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }
            for tool_call in tool_calls
        ]
