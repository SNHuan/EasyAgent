from typing import Any

from agent.tool_agent import ToolAgent
from debug.log import Color
from memory.base import BaseMemory
from model.base import BaseLLM
from model.schema import Message
from prompt.react import REACT_SYSTEM_PROMPT, REACT_END_TOKEN


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
        combined_prompt = self._build_system_prompt(system_prompt)
        super().__init__(model, combined_prompt, tools, memory)
        self._max_iterations = max_iterations

    def _build_system_prompt(self, user_prompt: str) -> str:
        """组合 ReAct 系统提示词和用户提示词"""
        if user_prompt:
            return f"{REACT_SYSTEM_PROMPT}\n\n{user_prompt}"
        return REACT_SYSTEM_PROMPT

    def _is_finished(self, content: str) -> bool:
        """检测输出是否包含终止符"""
        return REACT_END_TOKEN in content

    def _extract_final_answer(self, content: str) -> str:
        """提取终止符之前的最终回答"""
        if REACT_END_TOKEN in content:
            return content.split(REACT_END_TOKEN)[0].strip()
        return content

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

            # 检查是否包含终止符
            if self._is_finished(response.content):
                final_answer = self._extract_final_answer(response.content)
                self.add_message(Message.assistant(final_answer))
                if self._debug:
                    self._log.info(f"Final: {final_answer}", color=Color.CYAN)
                return final_answer

            # 无工具调用且无终止符，继续等待
            if not response.tool_calls:
                self.add_message(Message.assistant(response.content))
                if self._debug:
                    self._log.info(f"Response (no tool): {response.content}", color=Color.GRAY)
                continue

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
