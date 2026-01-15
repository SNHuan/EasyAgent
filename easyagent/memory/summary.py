import json
from pathlib import Path

import litellm

from easyagent.config.base import get_summary_model
from easyagent.memory.base import BaseMemory
from easyagent.model.schema import Message, content_to_text
from easyagent.prompt.memory import COMPRESS_SUMMARY_PROMPT, SUMMARY_FORMAT, SUMMARY_PROMPT


class SummaryMemory(BaseMemory):
    """Summary Memory: compresses messages when token count exceeds max_tokens"""

    def __init__(
        self,
        task_id: str,
        reserve_ratio: float = 0.3,
        model: str | None = None,
        workspace: str = "workspace",
    ):
        """
        Args:
            task_id: Task ID for storing summary file
            reserve_ratio: Token ratio reserved for recent messages after summary
            model: Model for summarization, also used to get max_tokens
            workspace: Working directory
        """
        self._task_id = task_id
        self._reserve_ratio = reserve_ratio
        self._model = model or get_summary_model()
        self._max_tokens = self._get_model_max_tokens()
        self._workspace = Path(workspace)
        self._messages: list[Message] = []
        self._token_counts: list[int] = []
        self._summary: str | None = None
        self._summary_tokens: int = 0

        self._workspace_path.mkdir(parents=True, exist_ok=True)
        self._load_existing_summary()

    def _get_model_max_tokens(self) -> int:
        """Get model's max_tokens from litellm"""
        try:
            return litellm.get_max_tokens(self._model)
        except Exception:
            return 8000  # fallback

    @property
    def _workspace_path(self) -> Path:
        return self._workspace / self._task_id

    @property
    def _summary_file(self) -> Path:
        return self._workspace_path / "summary.md"

    @property
    def _reserve_tokens(self) -> int:
        """Token count reserved for recent messages"""
        return int(self._max_tokens * self._reserve_ratio)

    def add(self, message: Message) -> None:
        tokens = self._count_tokens(message)
        self._messages.append(message)
        self._token_counts.append(tokens)

        if self.total_tokens > self._max_tokens:
            self._do_summary()

    def get_messages(self) -> list[Message]:
        msgs: list[Message] = []
        if self._summary:
            msgs.append(Message.system(f"Previous conversation summary:\n{self._summary}"))
        msgs.extend(self._messages)
        return msgs

    def clear(self) -> None:
        self._messages.clear()
        self._token_counts.clear()
        self._summary = None
        self._summary_tokens = 0
        if self._summary_file.exists():
            self._summary_file.unlink()

    @property
    def token_count(self) -> int:
        """Token count of current messages"""
        return sum(self._token_counts)

    @property
    def total_tokens(self) -> int:
        """Total token count (summary + messages)"""
        return self._summary_tokens + self.token_count

    def _count_tokens(self, message: Message) -> int:
        msg_dict = message.model_dump(exclude_none=True)
        return litellm.token_counter(model=self._model, messages=[msg_dict])

    def _count_text_tokens(self, text: str) -> int:
        return litellm.token_counter(model=self._model, text=text)

    def _load_existing_summary(self) -> None:
        if self._summary_file.exists():
            self._summary = self._summary_file.read_text(encoding="utf-8")
            self._summary_tokens = self._count_text_tokens(self._summary)

    @property
    def _summary_budget(self) -> int:
        """Token budget for summary (max_tokens - reserve_tokens)"""
        return self._max_tokens - self._reserve_tokens

    def _do_summary(self) -> None:
        """Execute summarization: compress old messages, keep recent ones, ensure total tokens <= max_tokens"""
        # Calculate recent messages to keep (from end, until reserve_tokens is reached)
        keep_count = 0
        keep_tokens = 0
        for tokens in reversed(self._token_counts):
            if keep_tokens + tokens > self._reserve_tokens:
                break
            keep_tokens += tokens
            keep_count += 1

        # Keep at least 1 recent message
        keep_count = max(keep_count, 1)

        to_summarize = self._messages[:-keep_count] if keep_count else self._messages
        to_keep = self._messages[-keep_count:] if keep_count else []
        tokens_to_keep = self._token_counts[-keep_count:] if keep_count else []

        if not to_summarize:
            # No messages to compress, try compressing existing summary
            if self._summary and self._summary_tokens > self._summary_budget:
                self._compress_summary()
            return

        conversation = self._format_conversation(to_summarize)
        prompt = SUMMARY_PROMPT.format(conversation=conversation)

        resp = litellm.completion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_summary = resp.choices[0].message.content or ""

        parsed = self._parse_summary(raw_summary)
        new_summary = SUMMARY_FORMAT.format(**parsed)

        if self._summary:
            new_summary = f"{self._summary}\n\n---\n\n{new_summary}"

        self._summary = new_summary
        self._summary_tokens = self._count_text_tokens(self._summary)

        # If summary still exceeds budget, perform secondary compression
        if self._summary_tokens > self._summary_budget:
            self._compress_summary()

        self._save_summary()
        self._messages = list(to_keep)
        self._token_counts = list(tokens_to_keep)

    def _compress_summary(self) -> None:
        """Compress the summary itself to fit within summary_budget"""
        if not self._summary:
            return

        prompt = COMPRESS_SUMMARY_PROMPT.format(
            target_tokens=self._summary_budget,
            summary=self._summary,
        )

        resp = litellm.completion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content or ""

        parsed = self._parse_summary(raw)
        self._summary = SUMMARY_FORMAT.format(**parsed)
        self._summary_tokens = self._count_text_tokens(self._summary)

    def _format_conversation(self, messages: list[Message]) -> str:
        lines = []
        for m in messages:
            role = m.role.upper()
            content_text = content_to_text(m.content)
            content = content_text[:500] if len(content_text) > 500 else content_text
            lines.append(f"[{role}]: {content}")
            if m.tool_calls:
                lines.append(f"  Tool calls: {m.tool_calls}")
        return "\n".join(lines)

    def _parse_summary(self, raw: str) -> dict:
        """Extract JSON from LLM response"""
        default = {
            "task_context": "N/A",
            "key_decisions": "N/A",
            "actions_taken": "N/A",
            "current_state": "N/A",
            "important_info": "N/A",
        }
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                for k, v in data.items():
                    if isinstance(v, list):
                        data[k] = "\n".join(f"- {item}" for item in v)
                return {**default, **data}
        except (json.JSONDecodeError, KeyError):
            pass
        return {**default, "task_context": raw[:500]}

    def _save_summary(self) -> None:
        self._summary_file.write_text(self._summary or "", encoding="utf-8")

