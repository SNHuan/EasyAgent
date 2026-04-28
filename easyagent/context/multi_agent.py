"""Multi-agent prompt formatter.

Migrated from ``easyagent.chat.formatter``. Folds non-self messages
into a ``<history>`` block so each LLM sees others' messages as
attributed conversation history rather than confusing them with its
own previous outputs.

Used by ``LLMEntity`` when building agent prompts in multi-agent
settings.
"""

from __future__ import annotations

from typing import Any

from easyagent.context.base import BaseContext
from easyagent.context.sliding import _drop_orphan_tool_messages
from easyagent.memory.base import BaseMemory
from easyagent.model.schema import Message

__all__ = ["MultiAgentFormatter"]

_DEFAULT_HISTORY_PREAMBLE = (
    "# Conversation History\n"
    "The lines inside <history></history> are what the other "
    "participants said. They are NOT your own previous turns; "
    "respond as yourself.\n"
)


class MultiAgentFormatter(BaseContext):
    """Render a multi-speaker memory into a self-coherent prompt for one
    agent.

    Args:
        self_name: Messages with this name are emitted as
            ``role=assistant``; everyone else's are folded.
        max_messages: Sliding-window cap applied before folding.
        history_preamble: Text prepended to folded user messages.
        history_tag: XML-style tag bracketing folded lines.
        fold_self_with_others: When True, self-turns are also folded.
    """

    def __init__(
        self,
        *,
        self_name: str,
        max_messages: int | None = 20,
        history_preamble: str = _DEFAULT_HISTORY_PREAMBLE,
        history_tag: str = "history",
        fold_self_with_others: bool = False,
    ) -> None:
        if not self_name:
            raise ValueError("MultiAgentFormatter requires a non-empty self_name")
        self._self_name = self_name
        self._max_messages = max_messages
        self._history_preamble = history_preamble
        self._history_tag = history_tag
        self._fold_self = fold_self_with_others

    @property
    def self_name(self) -> str:
        return self._self_name

    async def build_messages(
        self,
        memory: BaseMemory,
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        msgs = list(memory.get_all())
        if self._max_messages is not None:
            msgs = msgs[-self._max_messages :]

        msgs = _drop_orphan_tool_messages(msgs)

        rendered: list[dict[str, Any]] = []
        if system_prompt:
            rendered.append({"role": "system", "content": system_prompt})

        buf: list[Message] = []

        def flush() -> None:
            if not buf:
                return
            lines = []
            for m in buf:
                speaker = m.name or _role_label(m.role)
                line_text = m.text() if hasattr(m, "text") else str(m.content)
                lines.append(f"{speaker}: {line_text}")
            body = "\n".join(lines)
            wrapped = f"<{self._history_tag}>\n{body}\n</{self._history_tag}>"
            content = (
                f"{self._history_preamble}{wrapped}"
                if self._history_preamble
                else wrapped
            )
            rendered.append({"role": "user", "content": content})
            buf.clear()

        for m in msgs:
            if m.role == "tool" or (m.role == "assistant" and m.tool_calls):
                flush()
                rendered.append(m.to_api_dict())
                continue

            if m.role == "system":
                flush()
                rendered.append(m.to_api_dict())
                continue

            is_self = m.role == "assistant" or (
                m.name is not None and m.name == self._self_name
            )
            if is_self and not self._fold_self:
                flush()
                rendered.append({"role": "assistant", "content": m.text()})
                continue

            buf.append(m)

        flush()
        return rendered

    def clone(self) -> BaseContext:
        return MultiAgentFormatter(
            self_name=self._self_name,
            max_messages=self._max_messages,
            history_preamble=self._history_preamble,
            history_tag=self._history_tag,
            fold_self_with_others=self._fold_self,
        )


def _role_label(role: str) -> str:
    if role == "user":
        return "user"
    if role == "system":
        return "system"
    if role == "tool":
        return "tool"
    return role
