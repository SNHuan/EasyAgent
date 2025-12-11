from typing import Any

from agent.tool_agent import ToolAgent
from log import Color
from memory.base import BaseMemory
from model.base import BaseLLM
from model.schema import Message


class ReactAgent(ToolAgent):
    """ReAct 风格 Agent：think → act → observe 循环"""

    def __init__(
        self,
        model: BaseLLM,
        system_prompt: str = "",
        tools: list[str] | None = None,
        max_iterations: int = 10,
        memory: BaseMemory | None = None,
    ):
        super().__init__(model, system_prompt, tools, memory)
        self._max_iterations = max_iterations

    async def run(self, user_input: str) -> str:
        self.add_message(Message.user(user_input))
        if self._debug:
            self._log.debug(f"User: {user_input}")

        for i in range(self._max_iterations):
            msgs = self._build_messages()
            kwargs: dict[str, Any] = {}
            if schema := self._get_tools_schema():
                kwargs["tools"] = schema

            if self._debug:
                self._log.debug(f"Iteration {i + 1}/{self._max_iterations}")

            response = await self._model.call_with_history(msgs, **kwargs)

            if not response.tool_calls:
                self.add_message(Message.assistant(response.content))
                if self._debug:
                    self._log.info(f"Final: {response.content}", color=Color.CYAN)
                return response.content

            formatted = self._format_tool_calls(response.tool_calls)
            self.add_message(Message.assistant(response.content, formatted))

            for tc in response.tool_calls:
                if self._debug:
                    self._log.info(f"Tool call: {tc.name}({tc.arguments})", color=Color.YELLOW)
                result = self._execute_tool(tc.name, tc.arguments)
                if self._debug:
                    self._log.info(f"Tool result: {result}", color=Color.GREEN)
                self.add_message(Message.tool(result, tc.id))

        return "Max iterations reached"
