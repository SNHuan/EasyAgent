from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from easyagent.model.schema import LLMResponse, LLMStreamChunk


class BaseLLM(ABC):
    @abstractmethod
    async def call(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Single call: user_prompt + optional system_prompt -> response"""
        pass

    @abstractmethod
    async def call_with_history(
        self,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """Call with message history for multi-turn conversations"""
        pass

    async def stream(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream a single call.

        Base implementation falls back to the non-streaming call, so custom
        model adapters remain source-compatible until they opt into true
        provider streaming.
        """
        response = await self.call(user_prompt, system_prompt, **kwargs)
        if response.content:
            yield LLMStreamChunk(content=response.content)
        yield LLMStreamChunk(done=True, response=response)

    async def call_with_history_stream(
        self,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream a call with message history."""
        response = await self.call_with_history(messages, **kwargs)
        if response.content:
            yield LLMStreamChunk(content=response.content)
        yield LLMStreamChunk(done=True, response=response)
