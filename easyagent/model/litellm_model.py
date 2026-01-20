import json
import warnings
from typing import Any

import litellm

# Suppress Pydantic serialization warnings from litellm
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

from easyagent.config.base import ModelConfig, is_debug
from easyagent.debug.log import Color, Logger
from easyagent.model.base import BaseLLM
from easyagent.model.schema import LLMResponse, ToolCall

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


def _parse_args(arguments: str) -> dict[str, Any]:
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return {"raw": arguments}

