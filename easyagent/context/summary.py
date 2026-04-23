from __future__ import annotations

from easyagent.context.base import BaseContext
from easyagent.memory.base import BaseMemory
from easyagent.model.base import BaseLLM
from easyagent.model.schema import content_to_text
from easyagent.prompt.memory import SUMMARY_PROMPT


class SummaryContext(BaseContext):
    def __init__(self, summary_model: BaseLLM, reserve_recent: int = 10):
        self._summary_model = summary_model
        self._reserve_recent = reserve_recent
        self._cached_summary: str | None = None
        self._summarized_upto: int = 0

    async def build_messages(
        self,
        memory: BaseMemory,
        system_prompt: str,
    ) -> list[dict[str, str]]:
        all_messages = memory.get_all()
        if len(all_messages) <= self._reserve_recent:
            result: list[dict[str, str]] = []
            if system_prompt:
                result.append({"role": "system", "content": system_prompt})
            result.extend(message.to_api_dict() for message in all_messages)
            return result

        split_index = max(len(all_messages) - self._reserve_recent, 0)
        old_messages = all_messages[:split_index]
        recent_messages = all_messages[split_index:]

        if len(old_messages) > self._summarized_upto:
            self._cached_summary = await self._summarize(old_messages)
            self._summarized_upto = len(old_messages)

        result: list[dict[str, str]] = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        if self._cached_summary:
            result.append(
                {
                    "role": "system",
                    "content": f"Previous conversation summary:\n{self._cached_summary}",
                }
            )
        result.extend(message.to_api_dict() for message in recent_messages)
        return result

    async def _summarize(self, messages) -> str:
        conversation = []
        for message in messages:
            conversation.append(f"[{message.role.upper()}] {content_to_text(message.content)}")
        prompt = SUMMARY_PROMPT.format(conversation="\n".join(conversation))
        response = await self._summary_model.call(prompt)
        return response.content.strip()

    def clone(self) -> BaseContext:
        return SummaryContext(
            summary_model=self._summary_model,
            reserve_recent=self._reserve_recent,
        )
