from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Self, TypeVar


class BaseHook:
    """One awaited interception point in agent execution."""

    def apply(self, result: Any) -> Self:
        if result is not None:
            raise TypeError(f"{type(self).__name__} does not accept handler results")
        return self

    @property
    def stopped(self) -> bool:
        return False


H = TypeVar("H", bound=BaseHook)
HookHandler = Callable[[H], Any]


class HookManager:
    """Run control-plane hook handlers sequentially.

    Unlike EventBus observers, hook failures propagate to the caller. Each
    hook type owns how handler results are composed through ``apply``.
    """

    def __init__(self) -> None:
        self._handlers: list[tuple[type[BaseHook], HookHandler[Any]]] = []

    def on(self, hook_type: type[H], handler: HookHandler[H]) -> Callable[[], None]:
        self._handlers.append((hook_type, handler))

        def unsubscribe() -> None:
            self.off(hook_type, handler)

        return unsubscribe

    def off(self, hook_type: type[H], handler: HookHandler[H]) -> None:
        for index, registered in enumerate(self._handlers):
            if registered == (hook_type, handler):
                self._handlers.pop(index)
                return

    async def emit(self, hook: H) -> H:
        current = hook
        handlers = tuple(
            handler
            for hook_type, handler in self._handlers
            if isinstance(hook, hook_type)
        )
        for handler in handlers:
            result = handler(current)
            if inspect.isawaitable(result):
                result = await result
            current = current.apply(result)
            if current.stopped:
                return current
        return current

    def clear(self) -> None:
        self._handlers.clear()
