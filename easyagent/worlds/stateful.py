"""StatefulWorld — decorator that adds shared key-value state.

``SharedState`` is migrated from ``easyagent.chat.shared_state`` with
the same API (put/get/has/subscribe/wait_for) but stripped of chat-
layer coupling.

``StatefulWorld`` wraps any inner World, adding a ``StateSlice`` to
every Perception and handling ``SetState`` actions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from easyagent.core.types import (
    Action,
    Perception,
    PerceptionSlice,
    SetState,
    StateSlice,
)
from easyagent.core.world import AdvancingWorld, TickAwareWorld

if TYPE_CHECKING:
    from easyagent.core.world import World
    from easyagent.events.bus import EventBus

__all__ = ["SharedState", "StatefulWorld", "StateChangedEvent"]


Unsubscribe = Callable[[], None]
_Handler = Callable[[Any], "Any | Awaitable[Any]"]


# ── StateChangedEvent ──────────────────────────────────────────────────

from easyagent.events.base import BaseEvent


@dataclass
class StateChangedEvent(BaseEvent):
    key: str = ""
    value: Any = None
    version: int = 0
    producer: str | None = None


# ── SharedState ────────────────────────────────────────────────────────

@dataclass
class _Revision:
    version: int
    value: Any
    producer: str | None = None


class SharedState:
    """Versioned key/value store with subscribe + wait_for + bus."""

    def __init__(self) -> None:
        self._revisions: dict[str, list[_Revision]] = {}
        self._lock = Lock()
        self._subscribers: dict[str, list[_Handler]] = {}
        self._waits: dict[str, list[asyncio.Event]] = {}
        self._bus: EventBus | None = None

    def put(
        self,
        key: str,
        value: Any,
        *,
        producer: str | None = None,
    ) -> int:
        with self._lock:
            revs = self._revisions.setdefault(key, [])
            version = len(revs) + 1
            revs.append(_Revision(version=version, value=value, producer=producer))
            handlers = list(self._subscribers.get(key, []))
            waiters = list(self._waits.get(key, []))

        self._dispatch(handlers, value)
        for ev in waiters:
            try:
                ev.set()
            except Exception:  # noqa: BLE001
                pass

        if self._bus is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._bus.publish(
                        StateChangedEvent(
                            key=key, value=value, version=version, producer=producer
                        )
                    )
                )
            except RuntimeError:
                pass
        return version

    def get(self, key: str, *, version: int | None = None) -> Any:
        with self._lock:
            revs = self._revisions.get(key)
            if not revs:
                raise KeyError(key)
            if version is None:
                return revs[-1].value
            for rev in revs:
                if rev.version == version:
                    return rev.value
            raise KeyError(f"{key}@{version}")

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._revisions

    def history(self, key: str) -> list[tuple[int, Any, str | None]]:
        with self._lock:
            revs = self._revisions.get(key, [])
            return [(r.version, r.value, r.producer) for r in revs]

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._revisions.keys())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                k: revs[-1].value for k, revs in self._revisions.items() if revs
            }

    def subscribe(self, key: str, handler: _Handler) -> Unsubscribe:
        with self._lock:
            self._subscribers.setdefault(key, []).append(handler)

        def _unsubscribe() -> None:
            with self._lock:
                handlers = self._subscribers.get(key, [])
                try:
                    handlers.remove(handler)
                except ValueError:
                    pass

        return _unsubscribe

    async def wait_for(
        self,
        key: str,
        predicate: Callable[[Any], bool] | None = None,
        timeout: float | None = None,
    ) -> Any:
        check = predicate or (lambda _v: True)

        if self.has(key):
            v = self.get(key)
            if check(v):
                return v

        while True:
            event = asyncio.Event()
            with self._lock:
                self._waits.setdefault(key, []).append(event)

            try:
                if timeout is None:
                    await event.wait()
                else:
                    await asyncio.wait_for(event.wait(), timeout=timeout)
            finally:
                with self._lock:
                    waiters = self._waits.get(key, [])
                    try:
                        waiters.remove(event)
                    except ValueError:
                        pass

            v = self.get(key)
            if check(v):
                return v

    def attach_bus(self, bus: "EventBus") -> None:
        self._bus = bus

    def _dispatch(self, handlers: list[_Handler], value: Any) -> None:
        for h in handlers:
            try:
                result = h(value)
            except Exception:  # noqa: BLE001
                continue
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    result.close()


# ── StatefulWorld ──────────────────────────────────────────────────────


class StatefulWorld:
    """Decorator that adds StateSlice perception and SetState handling."""

    def __init__(self, inner: "World", state: SharedState | None = None) -> None:
        self.inner = inner
        self.state = state or SharedState()

    def observe(self, entity_id: str) -> Perception:
        base = self.inner.observe(entity_id)
        snapshot = tuple(self.state.snapshot().items())
        extra: PerceptionSlice = StateSlice(snapshot=snapshot)
        return Perception(
            entity_id=base.entity_id,
            tick=base.tick,
            slices=(*base.slices, extra),
        )

    def apply(self, entity_id: str, action: Action) -> None:
        if isinstance(action, SetState):
            self.state.put(action.key, action.value, producer=entity_id)
        else:
            self.inner.apply(entity_id, action)

    def seed(self, content: str, *, sender: str = "user") -> None:
        self.inner.seed(content, sender=sender)

    def set_tick(self, tick: int) -> None:
        if isinstance(self.inner, TickAwareWorld):
            self.inner.set_tick(tick)

    def advance(self, tick: int) -> None:
        if isinstance(self.inner, AdvancingWorld):
            self.inner.advance(tick)
