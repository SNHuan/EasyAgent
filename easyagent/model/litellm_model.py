import json
import warnings
from typing import Any, AsyncIterator

import litellm

# Suppress Pydantic serialization warnings from litellm
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

from easyagent.config.base import ModelConfig, is_debug
from easyagent.debug.log import Color, Logger
from easyagent.model.base import BaseLLM
from easyagent.model.schema import LLMResponse, LLMStreamChunk, ToolCall

_log = Logger("LiteLLM")


class LiteLLMModel(BaseLLM):
    def __init__(self, model: str, **kwargs):
        model_cfg = self._load_model_config(model)
        self._model = model_cfg.pop("model")
        self._kwargs = {**model_cfg, **kwargs}

    @staticmethod
    def _load_model_config(model: str) -> dict[str, Any]:
        try:
            return ModelConfig.load().get_model(model)
        except (FileNotFoundError, KeyError):
            # config 不存在或模型未配置，直接使用原始模型名
            return {"model": model}

    async def call(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        return await self._do_call(messages, **kwargs)

    async def call_with_history(
        self,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        return await self._do_call(messages, **kwargs)

    async def stream(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        async for chunk in self._do_stream(messages, **kwargs):
            yield chunk

    async def call_with_history_stream(
        self,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        async for chunk in self._do_stream(messages, **kwargs):
            yield chunk

    async def _do_call(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        merged_kwargs = {**self._kwargs, **kwargs}

        if is_debug():
            _log.debug(f"Request: model={self._model}, messages={len(messages)}")

        resp = await litellm.acompletion(model=self._model, messages=messages, **merged_kwargs)
        choice = resp.choices[0].message

        tool_calls = None
        if choice.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    type=tc.type,
                    name=tc.function.name,
                    arguments=_parse_args(tc.function.arguments),
                )
                for tc in choice.tool_calls
            ]

        usage = resp.usage.model_dump() if resp.usage else {}
        cost = litellm.completion_cost(completion_response=resp)

        if is_debug():
            tokens = f"in={usage.get('prompt_tokens', 0)}, out={usage.get('completion_tokens', 0)}"
            _log.info(f"Response: {tokens}, cost=${cost:.6f}", color=Color.MAGENTA)

        return LLMResponse(
            content=choice.content or "",
            reasoning_content=getattr(choice, "reasoning_content", None),
            tool_calls=tool_calls,
            usage={**usage, "cost": cost},
        )

    async def _do_stream(
        self,
        messages: list[dict[str, Any]],
        **kwargs,
    ) -> AsyncIterator[LLMStreamChunk]:
        merged_kwargs = {**self._kwargs, **kwargs, "stream": True}
        merged_kwargs.setdefault("stream_options", {"include_usage": True})

        if is_debug():
            _log.debug(f"Stream request: model={self._model}, messages={len(messages)}")

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}

        stream = await litellm.acompletion(model=self._model, messages=messages, **merged_kwargs)
        async for raw_chunk in stream:
            if getattr(raw_chunk, "usage", None):
                usage = raw_chunk.usage.model_dump()

            if not getattr(raw_chunk, "choices", None):
                continue
            delta = raw_chunk.choices[0].delta

            content = getattr(delta, "content", None) or ""
            reasoning = getattr(delta, "reasoning_content", None) or ""
            if content:
                content_parts.append(content)
            if reasoning:
                reasoning_parts.append(reasoning)
            if content or reasoning:
                yield LLMStreamChunk(
                    content=content,
                    reasoning_content=reasoning or None,
                )

            for tool_delta in getattr(delta, "tool_calls", None) or []:
                _merge_tool_call_delta(tool_call_parts, tool_delta)

        response = LLMResponse(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts) or None,
            tool_calls=_build_tool_calls(tool_call_parts),
            usage=usage,
        )
        yield LLMStreamChunk(done=True, response=response)


def _parse_args(arguments: str) -> dict[str, Any]:
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return {"raw": arguments}


def _merge_tool_call_delta(parts: dict[int, dict[str, Any]], delta: Any) -> None:
    index = int(getattr(delta, "index", len(parts)))
    current = parts.setdefault(index, {"id": "", "type": "function", "name": "", "arguments": ""})
    if getattr(delta, "id", None):
        current["id"] = delta.id
    if getattr(delta, "type", None):
        current["type"] = delta.type
    function = getattr(delta, "function", None)
    if function is None:
        return
    if getattr(function, "name", None):
        current["name"] += function.name
    if getattr(function, "arguments", None):
        current["arguments"] += function.arguments


def _build_tool_calls(parts: dict[int, dict[str, Any]]) -> list[ToolCall] | None:
    if not parts:
        return None
    tool_calls: list[ToolCall] = []
    for index in sorted(parts):
        item = parts[index]
        if not item.get("name"):
            continue
        tool_calls.append(
            ToolCall(
                id=item.get("id") or f"call_{index}",
                type=item.get("type") or "function",
                name=item["name"],
                arguments=_parse_args(item.get("arguments", "")),
            )
        )
    return tool_calls or None

