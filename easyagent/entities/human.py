"""HumanEntity — interactive entity driven by external input.

``act()`` reads from an ``asyncio.Queue`` or a callback function.
Useful for interactive flows and testing.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from easyagent.core.types import Action, Perception, Speak

__all__ = ["HumanEntity"]


class HumanEntity:
    """Entity that gets its actions from a human (or test harness)."""

    def __init__(
        self,
        entity_id: str,
        *,
        input_fn: Callable[[Perception], Awaitable[str | None]] | None = None,
        queue: asyncio.Queue[str | None] | None = None,
    ) -> None:
        self._id = entity_id
        self._input_fn = input_fn
        self._queue = queue

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> Action | None:
        text: str | None = None

        if self._input_fn is not None:
            text = await self._input_fn(perception)
        elif self._queue is not None:
            text = await self._queue.get()

        if text is None or not text.strip():
            return None
        return Speak(content=text)
