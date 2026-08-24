import pytest

from easyagent import AgentSession, BeforeToolCallHook, BeforeToolCallResult, HookManager
from easyagent.hooks import BaseHook


@pytest.mark.asyncio
async def test_hook_handlers_follow_global_registration_order() -> None:
    hooks = HookManager()
    observed: list[str] = []

    hooks.on(BaseHook, lambda hook: observed.append("base"))
    hooks.on(BeforeToolCallHook, lambda hook: observed.append("specific"))

    await hooks.emit(
        BeforeToolCallHook(
            session=AgentSession(),
            tool_name="echo",
            arguments={},
        )
    )

    assert observed == ["base", "specific"]


@pytest.mark.asyncio
async def test_hook_dispatch_uses_a_snapshot_when_handler_unsubscribes() -> None:
    hooks = HookManager()
    observed: list[str] = []
    unsubscribe = None

    def first(hook: BeforeToolCallHook) -> BeforeToolCallResult:
        observed.append("first")
        assert unsubscribe is not None
        unsubscribe()
        return BeforeToolCallResult(arguments={"value": "rewritten"})

    def second(hook: BeforeToolCallHook) -> None:
        observed.append(f"second:{hook.arguments['value']}")

    unsubscribe = hooks.on(BeforeToolCallHook, first)
    hooks.on(BeforeToolCallHook, second)
    original = BeforeToolCallHook(
        session=AgentSession(),
        tool_name="echo",
        arguments={"value": "original"},
    )

    await hooks.emit(original)
    await hooks.emit(original)

    assert observed == ["first", "second:rewritten", "second:original"]
