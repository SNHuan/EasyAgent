from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Callable, TypeVar

from easyagent.events.base import BaseEvent

T = TypeVar("T", bound=BaseEvent)
_log = logging.getLogger(__name__)


class EventBus:
    """Passive async event bus with in-memory history.

    - publish(event)          push an event; notifies all matching subscribers
    - subscribe(type, fn)     register a sync or async handler for an event type
    - history(type=None)      return all recorded events, optionally filtered
    - stream()                async-iterate future events (for frontend / replay)

    Subscribers are observers: their return values are ignored and their
    failures are isolated. Execution control belongs in the HookManager.
    """

    def __init__(self) -> None:
        self._history: list[BaseEvent] = []
        self._subscribers: dict[type, list[Callable[..., Any]]] = defaultdict(list)
        self._stream_queues: list[asyncio.Queue[BaseEvent | None]] = []

    async def publish(self, event: BaseEvent) -> None:
        self._history.append(event)

        # Notify all subscribers whose registered type appears in the MRO
        for klass in type(event).__mro__:
            for handler in self._subscribers.get(klass, []):
                try:
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
                except asyncio.CancelledError:
                    current_task = asyncio.current_task()
                    if current_task is not None and current_task.cancelling():
                        raise
                    _log.exception(
                        "Event observer %r was cancelled for %s",
                        handler,
                        type(event).__name__,
                    )
                except Exception:
                    _log.exception(
                        "Event observer %r failed for %s",
                        handler,
                        type(event).__name__,
                    )

        # Wake up any active stream consumers
        for q in self._stream_queues:
            await q.put(event)

    def subscribe(self, event_type: type[T], handler: Callable[[T], Any]) -> None:
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type[T], handler: Callable[[T], Any]) -> None:
        handlers = self._subscribers.get(event_type, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    def history(self, event_type: type[T] | None = None) -> list[T]:
        if event_type is None:
            return list(self._history)  # type: ignore[return-value]
        return [e for e in self._history if isinstance(e, event_type)]

    async def stream(self):
        """Async-iterate events as they are published."""
        queue: asyncio.Queue[BaseEvent | None] = asyncio.Queue()
        self._stream_queues.append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._stream_queues.remove(queue)

    def close(self) -> None:
        """Signal all active stream consumers to stop."""
        for q in self._stream_queues:
            q.put_nowait(None)
