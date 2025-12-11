from abc import ABC, abstractmethod
from typing import Any

from model.schema import LLMResponse


class BaseLLM(ABC):
    @abstractmethod
    async def call(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """单次调用：user_prompt + 可选 system_prompt -> response"""
        pass

    @abstractmethod
    async def call_with_history(
        self,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """带历史消息的调用，用于多轮对话"""
        pass
