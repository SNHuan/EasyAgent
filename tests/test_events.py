import asyncio

import pytest

from easyagent import EventBus, MessageEvent


@pytest.mark.asyncio
async def test_event_observer_failure_does_not_change_publish_outcome() -> None:
    bus = EventBus()
    observed: list[str] = []

    async def failing_observer(event: MessageEvent) -> None:
        raise RuntimeError("telemetry failed")

    async def healthy_observer(event: MessageEvent) -> None:
        observed.append(event.content)

    bus.subscribe(MessageEvent, failing_observer)
    bus.subscribe(MessageEvent, healthy_observer)

    await bus.publish(MessageEvent(sender="user", content="hello"))

    assert observed == ["hello"]
    assert [event.content for event in bus.history(MessageEvent)] == ["hello"]


@pytest.mark.asyncio
async def test_async_observer_cancellation_is_isolated() -> None:
    bus = EventBus()
    observed: list[str] = []

    async def cancelled_observer(event: MessageEvent) -> None:
        raise asyncio.CancelledError

    async def healthy_observer(event: MessageEvent) -> None:
        observed.append(event.content)

    bus.subscribe(MessageEvent, cancelled_observer)
    bus.subscribe(MessageEvent, healthy_observer)

    await bus.publish(MessageEvent(sender="user", content="hello"))

    assert observed == ["hello"]


@pytest.mark.asyncio
async def test_publisher_cancellation_still_propagates() -> None:
    bus = EventBus()
    observer_started = asyncio.Event()
    release_observer = asyncio.Event()

    async def slow_observer(event: MessageEvent) -> None:
        observer_started.set()
        await release_observer.wait()

    bus.subscribe(MessageEvent, slow_observer)
    publisher = asyncio.create_task(
        bus.publish(MessageEvent(sender="user", content="hello"))
    )
    await observer_started.wait()

    publisher.cancel()

    with pytest.raises(asyncio.CancelledError):
        await publisher


@pytest.mark.asyncio
async def test_observer_return_value_is_ignored() -> None:
    bus = EventBus()
    observed: list[str] = []

    def attempted_control(event: MessageEvent) -> object:
        return object()

    def healthy_observer(event: MessageEvent) -> None:
        observed.append(event.content)

    bus.subscribe(MessageEvent, attempted_control)
    bus.subscribe(MessageEvent, healthy_observer)

    assert await bus.publish(MessageEvent(sender="user", content="hello")) is None
    assert observed == ["hello"]
