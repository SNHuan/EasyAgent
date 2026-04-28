"""Multi-agent prompt formatter.

A standard ``SlidingWindowContext`` works fine for single-agent
conversations, but in a group chat each ``Message`` carries a
``name`` distinguishing speakers. If we hand those messages straight
to the LLM API:

  - ``role=assistant`` + ``name=alice`` looks like *I, the model
    being prompted now (bob), said this earlier* — the LLM happily
    mistakes alice's words for its own.
  - ``role=user``      + ``name=alice`` looks like a single user
    suddenly named alice — providers tolerate it but it's weak signal.

The standard fix (used by AgentScope's ``MultiAgentFormatter``,
imitated here) is to fold every "non-self" turn into a single user
message containing a ``<history>`` block that explicitly attributes
each line:

    role: user
    content: |
      # Conversation History
      <history>
      alice: I propose Tahoe.
      carol: Too far. Beach instead?
      </history>

Self-turns stay as ``role=assistant`` so the LLM continues to see its
own past output as its own. System prompts pass through. Tool-call
sequences (assistant with ``tool_calls`` + the matching ``role=tool``
results) pass through too — splitting them into a history fold would
break the API contract.

The formatter degrades gracefully: if every message in memory is
either system / self / unnamed-user, no folding happens and the output
is identical to ``SlidingWindowContext``. Single-agent code paths pay
no cost.
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

    Construct one per ``LLMTalker`` (since each talker has its own
    ``self_name``). Pass it into ``LLMTalker(..., formatter=...)`` or
    let the talker create its own — the talker installs the formatter
    onto its per-channel sessions before driving the agent loop.

    Args:
        self_name: The talker's own name. Messages with this ``name``
            are emitted as ``role=assistant`` (their natural form);
            everyone else's are folded.
        max_messages: Sliding-window cap applied *before* folding.
            ``None`` means no cap. Counts raw memory entries, so
            tool-call sequences are not over-trimmed.
        history_preamble: Text prepended to a folded user message to
            tell the LLM what the ``<history>`` block represents.
            Default explains the convention; pass ``""`` to suppress.
        history_tag: XML-style tag bracketing the folded lines.
        fold_self_with_others: When False (default), self-turns
            interrupt the fold — they're emitted in place as
            ``role=assistant``. When True, self-turns are folded too,
            which is occasionally useful when the agent should "see"
            its past statements at the same level as others' (e.g. a
            judge reviewing a transcript).
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

        # Walk the trimmed memory once. We accumulate "other-speaker"
        # text into ``buf`` and flush it as a single folded user
        # message whenever we hit something that *can't* be folded:
        # self-turns, system messages, and tool-call sequences.
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
            # Tool-call sequences must be passed through untouched.
            # An ``assistant`` with ``tool_calls`` and the matching
            # ``role=tool`` follow-ups are a single semantic unit.
            if m.role == "tool" or (m.role == "assistant" and m.tool_calls):
                flush()
                rendered.append(m.to_api_dict())
                continue

            if m.role == "system":
                flush()
                # Mid-conversation system messages are rare but legal
                # (hints from the agent itself). They are not folded.
                rendered.append(m.to_api_dict())
                continue

            is_self = m.role == "assistant" or (
                m.name is not None and m.name == self._self_name
            )
            if is_self and not self._fold_self:
                flush()
                # Self-turn: emit as assistant. We don't pass the
                # ``name`` field — keeping it bare matches what the
                # underlying agent loop produced and avoids surprises
                # with providers that reject ``name`` on assistant.
                rendered.append({"role": "assistant", "content": m.text()})
                continue

            # Everyone else: a user message (named or unnamed) goes
            # into the fold buffer.
            buf.append(m)

        flush()

        # If folding never produced anything beyond a system prompt,
        # we have a single-agent transcript — fall back to the
        # SlidingWindow-equivalent rendering. ``rendered`` is already
        # equivalent (no fold ever fired), so just return.
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
    """Fallback speaker label when a memory entry has no ``name``."""
    if role == "user":
        return "user"
    if role == "system":
        return "system"
    if role == "tool":
        return "tool"
    return role
