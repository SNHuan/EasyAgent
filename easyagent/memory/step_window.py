from __future__ import annotations

from typing import List

from easyagent.memory.base import BaseMemory
from easyagent.model.schema import Message


class StepWindowMemory(BaseMemory):
    """Memory strategy that limits history by user message steps, with optional image trimming."""

    def __init__(self, text_steps: int = 10, image_steps: int = 3) -> None:
        self._text_steps = text_steps
        self._image_steps = image_steps
        self._messages: List[Message] = []

    def add(self, message: Message) -> None:
        self._messages.append(message)

    def get_messages(self) -> list[Message]:
        messages = self._trim_text(self._messages)
        return self._trim_images(messages)

    def clear(self) -> None:
        self._messages.clear()

    @property
    def token_count(self) -> int:
        return len(self._messages)

    def _trim_text(self, messages: List[Message]) -> List[Message]:
        if self._text_steps is None or self._text_steps <= 0:
            return list(messages)
        user_indices = [idx for idx, msg in enumerate(messages) if msg.role == "user"]
        if len(user_indices) <= self._text_steps:
            return list(messages)
        start = user_indices[-self._text_steps]
        return list(messages[start:])

    def _trim_images(self, messages: List[Message]) -> List[Message]:
        if self._image_steps is None:
            return list(messages)

        user_positions = [idx for idx, msg in enumerate(messages) if msg.role == "user"]
        if self._image_steps <= 0:
            cutoff = len(messages)
        elif len(user_positions) > self._image_steps:
            cutoff = user_positions[-self._image_steps]
        else:
            return list(messages)

        trimmed: List[Message] = []
        for idx, msg in enumerate(messages):
            if msg.role == "user" and idx < cutoff:
                trimmed.append(_strip_images(msg))
            else:
                trimmed.append(msg)
        return trimmed


def _strip_images(message: Message) -> Message:
    content = message.content
    if isinstance(content, list):
        filtered = [
            item
            for item in content
            if not (isinstance(item, dict) and item.get("type") == "image_url")
        ]
        return message.model_copy(update={"content": filtered})
    if isinstance(content, dict):
        cleaned = dict(content)
        if "images" in cleaned:
            cleaned["images"] = []
        if "image_urls" in cleaned:
            cleaned["image_urls"] = []
        return message.model_copy(update={"content": cleaned})
    return message
