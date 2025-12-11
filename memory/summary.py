import json
from pathlib import Path

import litellm

from config.base import get_summary_model
from memory.base import BaseMemory
from model.schema import Message
from prompt.memory import COMPRESS_SUMMARY_PROMPT, SUMMARY_FORMAT, SUMMARY_PROMPT


class SummaryMemory(BaseMemory):
    """Summary Memory：token 数量达到 max_tokens 时进行摘要压缩"""

    def __init__(
        self,
        task_id: str,
        reserve_ratio: float = 0.3,
        model: str | None = None,
        workspace: str = "workspace",
    ):
        """
        Args:
            task_id: 任务 ID，用于存储 summary 文件
            reserve_ratio: summary 后保留的 token 比例（用于最近消息）
            model: summary 使用的模型，同时用于获取 max_tokens
            workspace: 工作目录
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
        """从 litellm 获取模型的 max_tokens"""
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
        """保留给最近消息的 token 数"""
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
        """当前消息的 token 数"""
        return sum(self._token_counts)

    @property
    def total_tokens(self) -> int:
        """总 token 数（summary + 消息）"""
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
        """summary 可用的 token 预算（max_tokens - reserve_tokens）"""
        return self._max_tokens - self._reserve_tokens

    def _do_summary(self) -> None:
        """执行摘要：压缩旧消息，保留最近消息，确保总 token 不超过 max_tokens"""
        # 计算需要保留的最近消息（从后往前，直到达到 reserve_tokens）
        keep_count = 0
        keep_tokens = 0
        for tokens in reversed(self._token_counts):
            if keep_tokens + tokens > self._reserve_tokens:
                break
            keep_tokens += tokens
            keep_count += 1

        # 至少保留 1 条最近消息
        keep_count = max(keep_count, 1)

        to_summarize = self._messages[:-keep_count] if keep_count else self._messages
        to_keep = self._messages[-keep_count:] if keep_count else []
        tokens_to_keep = self._token_counts[-keep_count:] if keep_count else []

        if not to_summarize:
            # 没有可压缩的消息，尝试压缩现有 summary
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

        # 如果 summary 仍然超过预算，进行二次压缩
        if self._summary_tokens > self._summary_budget:
            self._compress_summary()

        self._save_summary()
        self._messages = list(to_keep)
        self._token_counts = list(tokens_to_keep)

    def _compress_summary(self) -> None:
        """对 summary 本身进行压缩，使其不超过 summary_budget"""
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
            content = m.content[:500] if len(m.content) > 500 else m.content
            lines.append(f"[{role}]: {content}")
            if m.tool_calls:
                lines.append(f"  Tool calls: {m.tool_calls}")
        return "\n".join(lines)

    def _parse_summary(self, raw: str) -> dict:
        """从 LLM 响应中提取 JSON"""
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

