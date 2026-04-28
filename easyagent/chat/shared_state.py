"""Shared blackboard for multi-Talker collaboration.

The chat layer's primary collaboration mode is messages, but some
patterns (artifact-driven workshops, vote tallies, plan trees, async
tool results) are awkward as conversation. ``SharedState`` provides
the *other* primary primitive: a versioned key-value store with
subscriptions and async waits.

Capabilities:

  - versioned ``put`` / ``get`` / ``has`` / ``history`` / ``snapshot``
  - ``subscribe(key, handler)``: callback fires whenever ``key`` is
    written. Sync or async handlers welcome. Returns an unsubscribe
    callable.
  - ``wait_for(key, predicate)``: async wait until ``key``'s latest
    value satisfies ``predicate``.
  - ``attach_bus(bus)``: every write also publishes a
    ``StateChangedEvent`` for the EventBus so the UI/log layer can
    observe.

Talkers don't access SharedState through Talker protocol — they reach
it via tools (``put_state`` / ``get_state`` / ``wait_for_state``).
The Orchestrator threads it through ``TurnContext.shared`` so
strategies (``OnSharedKey``, ``FromSharedState``) can read.

Design refs: ``docs/chat_layer_design.md`` §7.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from easyagent.events.bus import EventBus


__all__ = ["SharedState", "StateChangedEvent", "Unsubscribe"]


Unsubscribe = Callable[[], None]
_Handler = Callable[[Any], "Any | Awaitable[Any]"]


# ── StateChangedEvent (lives in chat/ to avoid bloating events/) ─────────


# Imported lazily where needed; we declare it here so subscribers can
# match on type. The chat layer is the only producer.
from easyagent.events.base import BaseEvent


@dataclass
class StateChangedEvent(BaseEvent):
    """Fired by SharedState when a key is written. Carries enough to
    reconstruct the change without consulting the store. Subscribers
    on the bus see this just like any other event."""

    key: str = ""
    value: Any = None
    version: int = 0
    producer: str | None = None


# ── _Revision (private) ──────────────────────────────────────────────────


@dataclass
class _Revision:
    version: int
    value: Any
    producer: str | None = None


# ── SharedState ──────────────────────────────────────────────────────────


class SharedState:
    """Versioned key/value store with subscribe + wait_for + bus
    observability.

    Thread-safe for the synchronous parts (``put`` / ``get`` /
    ``has`` / ``history`` / ``snapshot``). Async parts (``wait_for``)
    rely on ``asyncio.Event`` per-key, which lives in the running
    event loop.

    Writes are append-only: every ``put`` adds a new revision, history
    is never erased. ``snapshot()`` returns the latest value per key
    for prompt embedding or debugging.

    Producer attribution: callers may pass ``producer="alice"`` so
    consumers can filter by who wrote a value.
    """

    def __init__(self) -> None:
        self._revisions: dict[str, list[_Revision]] = {}
        self._lock = Lock()
        # name → list of handlers (sync or coroutine functions)
        self._subscribers: dict[str, list[_Handler]] = {}
        # name → asyncio.Event used by wait_for; created lazily
        self._waits: dict[str, "list[asyncio.Event]"] = {}
        self._bus: "EventBus | None" = None

    # ── core (synchronous, thread-safe) ─────────────────────────────────

    def put(
        self,
        key: str,
        value: Any,
        *,
        producer: str | None = None,
    ) -> int:
        """Append a new revision; returns the assigned version (1-based).

        Triggers (in order):
          1. Sync subscribers run inline (in the calling thread).
          2. Coroutine subscribers are scheduled on the running loop.
          3. ``asyncio.Event`` waiters are signalled.
          4. ``StateChangedEvent`` is published on the bus if attached.
        """
        with self._lock:
            revs = self._revisions.setdefault(key, [])
            version = len(revs) + 1
            revs.append(_Revision(version=version, value=value, producer=producer))
            handlers = list(self._subscribers.get(key, []))
            waiters = list(self._waits.get(key, []))

        # Fire subscribers OUTSIDE the lock to avoid deadlocks if a
        # handler turns around and writes another key.
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
                # No running loop — bus publishing is a no-op outside
                # async contexts (the chat layer always runs inside one,
                # but ``put`` is also useful from sync setup code).
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

    # ── subscribe / wait_for ────────────────────────────────────────────

    def subscribe(self, key: str, handler: _Handler) -> Unsubscribe:
        """Register ``handler`` to fire on every future write of ``key``.

        Returns an unsubscribe callable — call it to detach. Handler
        receives the new value as its only argument.
        """
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
        """Wait until ``key`` exists and its latest value satisfies
        ``predicate`` (default: any value satisfies).

        Returns the satisfying value. Raises ``asyncio.TimeoutError``
        on timeout. Re-checks on every write — if multiple writes
        come and none satisfy, keeps waiting.
        """
        check = predicate or (lambda _v: True)  # noqa: ARG005

        # Fast path: already satisfied?
        if self.has(key):
            v = self.get(key)
            if check(v):
                return v

        # Slow path: wait for next write, re-check, repeat.
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
            # Predicate not yet satisfied; loop and wait for the next
            # write. ``timeout`` is per-iteration here — for a hard
            # deadline, callers should wrap with ``asyncio.wait_for``
            # outside.

    # ── bus integration ─────────────────────────────────────────────────

    def attach_bus(self, bus: "EventBus") -> None:
        """Route every future write through ``bus`` as a
        ``StateChangedEvent``. Detach via ``attach_bus(None)`` (using
        a sentinel-style override is not supported; rebuild the state
        if you really need to).
        """
        self._bus = bus

    # ── internals ───────────────────────────────────────────────────────

    def _dispatch(self, handlers: list[_Handler], value: Any) -> None:
        """Run subscribers without blocking on coroutine ones.

        Sync handlers run inline. Coroutine handlers are scheduled on
        the running loop if there is one; otherwise they're queued via
        ``asyncio.run`` is NOT used here — that would create a fresh
        loop and deadlock. Without a loop, coroutine handlers warn
        and skip. The chat layer always runs inside a loop, so this
        is just defensive.
        """
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
                    # No loop — close the coroutine to avoid
                    # ``RuntimeWarning: coroutine ... was never awaited``.
                    result.close()
