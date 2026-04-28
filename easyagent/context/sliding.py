from __future__ import annotations

from typing import Any

import litellm

from easyagent.context.base import BaseContext
from easyagent.memory.base import BaseMemory
from easyagent.model.schema import Message


def _drop_orphan_tool_messages(messages: list[Message]) -> list[Message]:
    """Remove tool-role messages whose assistant+tool_calls was sliced off.

    After a sliding-window cut the first messages may be 'tool' responses
    whose corresponding 'assistant' message with tool_calls no longer exists.
    The OpenAI API rejects such sequences with a 400 error.
    """
    declared_ids: set[str] = set()
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    declared_ids.add(tc_id)

    return [
        m for m in messages
        if m.role != "tool" or m.tool_call_id in declared_ids
    ]


class SlidingWindowContext(BaseContext):
    def __init__(
        self,
        *,
        max_messages: int | None = 20,
        max_tokens: int | None = None,
        model: str = "gpt-4o",
    ):
        self._max_messages = max_messages
        self._max_tokens = max_tokens
        self._model = model

    async def build_messages(
        self,
        memory: BaseMemory,
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        messages = memory.get_all()
        if self._max_messages is not None:
            messages = messages[-self._max_messages :]
        if self._max_tokens is not None:
            messages = self._trim_to_token_budget(messages, self._max_tokens)

        messages = _drop_orphan_tool_messages(messages)

        result: list[dict[str, Any]] = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        result.extend(message.to_api_dict() for message in messages)
        return result

    def _trim_to_token_budget(self, messages: list[Message], budget: int) -> list[Message]:
        trimmed = list(messages)
        while trimmed and self._count_tokens(trimmed) > budget:
            trimmed.pop(0)
        return trimmed

    def _count_tokens(self, messages: list[Message]) -> int:
        api_messages = [message.to_api_dict() for message in messages]
        return litellm.token_counter(model=self._model, messages=api_messages)

    def clone(self) -> BaseContext:
        return SlidingWindowContext(
            max_messages=self._max_messages,
            max_tokens=self._max_tokens,
            model=self._model,
        )
