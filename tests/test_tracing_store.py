from __future__ import annotations

import pytest

from easyagent import (
    EventBus,
    JSONLStore,
    MemoryStore,
    ReactAgent,
    SQLiteStore,
    TraceRecorder,
)
from easyagent.model.schema import LLMResponse


class FakeLLM:
    async def call_with_history(self, messages, **kwargs):
        return LLMResponse(
            content="done",
            usage={
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        )


class FailingLLM:
    async def call_with_history(self, messages, **kwargs):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_trace_recorder_persists_agent_run_to_memory_store():
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(model=FakeLLM(), max_iterations=2)
    result = await agent.run("hello", event_bus=bus)

    session = store.get_session(result.session.session_id)
    assert session is not None
    assert session.status == "completed"
    assert session.event_count == 4
    assert session.token_usage.total_tokens == 5

    events = store.list_events(result.session.session_id)
    assert [event.event_type for event in events] == [
        "AgentStartedEvent",
        "LLMCalledEvent",
        "LLMRespondedEvent",
        "AgentFinishedEvent",
    ]


@pytest.mark.asyncio
async def test_trace_recorder_marks_failed_sessions():
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(model=FailingLLM(), max_iterations=2)
    with pytest.raises(RuntimeError):
        await agent.run("hello", event_bus=bus)

    session = store.list_sessions()[0]
    assert session.status == "failed"
    assert store.list_events(session.session_id)[-1].event_type == "AgentFailedEvent"


@pytest.mark.asyncio
async def test_sqlite_store_round_trips_trace(tmp_path):
    store = SQLiteStore(tmp_path / "traces.db")
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(model=FakeLLM(), max_iterations=2)
    result = await agent.run("hello", event_bus=bus)

    sessions = store.list_sessions()
    assert [session.session_id for session in sessions] == [result.session.session_id]
    assert sessions[0].token_usage.prompt_tokens == 3
    assert store.list_events(result.session.session_id)[-1].event_type == "AgentFinishedEvent"


@pytest.mark.asyncio
async def test_jsonl_store_round_trips_trace(tmp_path):
    store = JSONLStore(tmp_path / "traces.jsonl")
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(model=FakeLLM(), max_iterations=2)
    result = await agent.run("hello", event_bus=bus)

    session = store.get_session(result.session.session_id)
    assert session is not None
    assert session.token_usage.completion_tokens == 2
    assert len(store.list_events(result.session.session_id)) == 4
