from typing import Any
import base64
import mimetypes
from pathlib import Path

from easyagent.agent.tool_agent import ToolAgent
from easyagent.debug.log import Color
from easyagent.memory.base import BaseMemory
from easyagent.model.base import BaseLLM
from easyagent.model.schema import Message, content_to_text
from easyagent.prompt.react import REACT_SYSTEM_PROMPT, REACT_END_TOKEN


class ReactAgent(ToolAgent):
    """ReAct-style Agent: think -> act -> observe loop"""

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
        """Combine ReAct system prompt with user prompt"""
        if user_prompt:
            return f"{REACT_SYSTEM_PROMPT}\n\n{user_prompt}"
        return REACT_SYSTEM_PROMPT

    def _is_finished(self, content: str) -> bool:
        """Check if output contains termination token"""
        return REACT_END_TOKEN in content

    def _extract_final_answer(self, content: str) -> str:
        """Extract final answer before termination token"""
        if REACT_END_TOKEN in content:
            return content.split(REACT_END_TOKEN)[0].strip()
        return content

    def _build_user_content(self, user_input: Any) -> Any:
        if isinstance(user_input, list):
            return user_input
        if isinstance(user_input, dict):
            text = str(user_input.get("text", ""))
            images = user_input.get("images") or user_input.get("image_urls") or []
            if images:
                content: list[dict[str, Any]] = []
                if text:
                    content.append({"type": "text", "text": text})
                for image in images:
                    content.append(self._normalize_image_part(image))
                return content
        return user_input
    

    @staticmethod
    def _normalize_image_part(image: Any) -> dict[str, Any]:
        if isinstance(image, dict):
            if image.get("type") == "image_url":
                return image
            if "image_url" in image:
                image_url = image["image_url"]
                if isinstance(image_url, str):
                    return {"type": "image_url", "image_url": {"url": image_url}}
                return {"type": "image_url", "image_url": image_url}
            if "url" in image:
                return {"type": "image_url", "image_url": {"url": image["url"]}}
            if "path" in image:
                return {"type": "image_url", "image_url": {"url": _path_to_data_url(image["path"])}}
        if isinstance(image, str):
            if _looks_like_path(image):
                return {"type": "image_url", "image_url": {"url": _path_to_data_url(image)}}
        return {"type": "image_url", "image_url": {"url": str(image)}}

    async def run(self, user_input: str | dict[str, Any] | list[dict[str, Any]]) -> str:
        content = self._build_user_content(user_input)
        self.add_message(Message.user(content))
        if self._debug:
            self._log.debug(f"User: {content_to_text(content)}")

        for i in range(self._max_iterations):
            msgs = self._build_messages()
            kwargs: dict[str, Any] = {}
            if schema := self._get_tools_schema():
                kwargs["tools"] = schema

            if self._debug:
                self._log.debug(f"Iteration {i + 1}/{self._max_iterations}")

            response = await self._model.call_with_history(msgs, **kwargs)

            # Check for termination token
            if self._is_finished(response.content):
                final_answer = self._extract_final_answer(response.content)
                self.add_message(Message.assistant(final_answer))
                if self._debug:
                    self._log.info(f"Final: {final_answer}", color=Color.CYAN)
                return final_answer

            # No tool calls and no termination token, continue
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
                result = await self._execute_tool(tc.name, tc.arguments)
                if self._debug:
                    self._log.info(f"Tool result: {result}", color=Color.GREEN)
                self.add_message(Message.tool(result, tc.id))

        return "Max iterations reached"

def _looks_like_path(value: str) -> bool:
    return not value.startswith(("http://", "https://", "data:"))


def _path_to_data_url(path_value: Any) -> str:
    path = Path(str(path_value)).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Image path not found: {path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "application/octet-stream"
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
