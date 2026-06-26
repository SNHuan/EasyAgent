from __future__ import annotations

import pytest

from easyagent import (
    ConversationWorld,
    CustomTraceEvent,
    DisplayHint,
    EventBus,
    LLMEntity,
    JSONLStore,
    MemoryStore,
    ReactAgent,
    Runtime,
    SQLiteStore,
    TakeTurns,
    TraceRecorder,
    register_token_usage_adapter,
)
from easyagent.dashboard.server import load_trace_payload
from easyagent.model.schema import LLMResponse, LLMStreamChunk


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


class FakeStreamingLLM(FakeLLM):
    async def call_with_history_stream(self, messages, **kwargs):
        yield LLMStreamChunk(content="he")
        yield LLMStreamChunk(content="llo")
        yield LLMStreamChunk(
            done=True,
            response=LLMResponse(
                content="hello",
                usage={
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            ),
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
async def test_trace_recorder_persists_stream_chunks():
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(model=FakeStreamingLLM(), max_iterations=2)
    chunks = [chunk async for chunk in agent.stream("hello", event_bus=bus)]

    session = store.list_sessions()[0]
    events = store.list_events(session.session_id)
    assert chunks == ["he", "llo"]
    assert [event.event_type for event in events] == [
        "AgentStartedEvent",
        "LLMCalledEvent",
        "LLMStreamChunkEvent",
        "LLMStreamChunkEvent",
        "LLMRespondedEvent",
        "AgentFinishedEvent",
    ]
    assert [event.payload["content"] for event in events if event.event_type == "LLMStreamChunkEvent"] == [
        "he",
        "llo",
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


@pytest.mark.asyncio
async def test_runtime_tracing_links_entity_agent_sessions():
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    entity = LLMEntity("planner", ReactAgent(model=FakeLLM(), max_iterations=2))
    runtime = Runtime(
        world=ConversationWorld(),
        entities={"planner": entity},
        schedule=TakeTurns(order=["planner"]),
        bus=bus,
        runtime_id="runtime_test",
        title="Runtime test",
    )

    result = await runtime.run("hello")
    assert result.ticks == 1

    runtime_trace = store.get_session("runtime_test")
    assert runtime_trace is not None
    assert runtime_trace.status == "completed"
    assert runtime_trace.metadata["trace_kind"] == "runtime"
    assert runtime_trace.metadata["run_id"] == "runtime_test"
    assert runtime_trace.metadata["world"]["kind"] == "ConversationWorld"

    agent_sessions = [
        session
        for session in store.list_sessions()
        if session.session_id != "runtime_test"
    ]
    assert len(agent_sessions) == 1
    agent_trace = agent_sessions[0]
    assert agent_trace.metadata["run_id"] == "runtime_test"
    assert agent_trace.metadata["run_scope"] == "runtime"
    assert agent_trace.metadata["entity"]["entity_id"] == "planner"
    assert agent_trace.token_usage.total_tokens == 5

    runtime_events = [event.event_type for event in store.list_events("runtime_test")]
    assert runtime_events == [
        "RuntimeStartedEvent",
        "RuntimeTickStartedEvent",
        "EntityStartedEvent",
        "EntityFinishedEvent",
        "MessageEvent",
        "RuntimeTickFinishedEvent",
        "RuntimeFinishedEvent",
    ]


def test_custom_trace_event_persists_event_type_payload_and_display_hint():
    store = MemoryStore()
    recorder = TraceRecorder(store)

    recorder.record(
        CustomTraceEvent(
            event_type="PlannerStepEvent",
            session_id="session_custom",
            agent_id="planner",
            summary="Planner selected search_docs",
            payload={"step": "search_docs"},
            display=DisplayHint.messages(
                "Need to inspect README and pyproject first.",
                role="assistant",
                title="Planner step",
                source="planner",
            ),
        )
    )

    session = store.get_session("session_custom")
    assert session is not None
    assert session.event_count == 1

    event = store.list_events("session_custom")[0]
    assert event.event_type == "PlannerStepEvent"
    assert event.agent_id == "planner"
    assert event.payload["summary"] == "Planner selected search_docs"
    assert event.payload["step"] == "search_docs"
    assert event.payload["display"] == {
        "surface": "messages",
        "role": "assistant",
        "title": "Planner step",
        "content": "Need to inspect README and pyproject first.",
        "source": "planner",
        "icon": None,
        "color": None,
        "priority": None,
        "metadata": {},
    }


def test_custom_trace_event_persists_dashboard_group_path_metadata() -> None:
    store = MemoryStore()
    recorder = TraceRecorder(store)

    recorder.record(
        CustomTraceEvent(
            event_type="ExternalAgentStartedEvent",
            session_id="session_grouped",
            agent_id="coder",
            summary="started",
            payload={
                "trace_kind": "external_agent",
                "run_id": "run_grouped",
                "entity": {"entity_id": "coder", "label": "Coder"},
                "dashboard_group_path": [
                    {"id": "repo:easyagent", "label": "EasyAgent", "kind": "repo"},
                    {"id": "task:dashboard-tree", "label": "Dashboard Tree", "kind": "task"},
                ],
            },
        )
    )

    session = store.get_session("session_grouped")
    assert session is not None
    assert session.metadata["dashboard_group_path"] == [
        {"id": "repo:easyagent", "label": "EasyAgent", "kind": "repo"},
        {"id": "task:dashboard-tree", "label": "Dashboard Tree", "kind": "task"},
    ]


def test_dashboard_trace_payload_projects_custom_group_path_tree(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "traces.db")
    recorder = TraceRecorder(store)

    for session_id, agent_id, label in (
        ("session_coder", "coder", "Coder"),
        ("session_reviewer", "reviewer", "Reviewer"),
    ):
        recorder.record(
            CustomTraceEvent(
                event_type="ExternalAgentStartedEvent",
                session_id=session_id,
                agent_id=agent_id,
                summary="started",
                payload={
                    "trace_kind": "external_agent",
                    "run_id": "run_grouped",
                    "run_title": "Grouped run",
                    "entity": {"entity_id": agent_id, "label": label, "kind": "agent"},
                    "dashboard_group_path": [
                        {"id": "repo:easyagent", "label": "EasyAgent", "kind": "repo"},
                        {"id": "task:dashboard-tree", "label": "Dashboard Tree", "kind": "task"},
                    ],
                },
            )
        )

    payload = load_trace_payload(tmp_path / "traces.db")

    run = payload["runs"][0]
    assert run["run_id"] == "run_grouped"
    repo_node = run["tree"][0]
    assert repo_node["id"] == "group:repo:easyagent"
    assert repo_node["label"] == "EasyAgent"
    assert repo_node["kind"] == "repo"
    assert repo_node["event_count"] == 2

    task_node = repo_node["children"][0]
    assert task_node["id"] == "group:task:dashboard-tree"
    assert task_node["label"] == "Dashboard Tree"
    assert task_node["kind"] == "task"
    assert task_node["event_count"] == 2

    entity_nodes = task_node["children"]
    assert [node["id"] for node in entity_nodes] == ["entity:coder", "entity:reviewer"]
    assert [node["label"] for node in entity_nodes] == ["Coder", "Reviewer"]
    assert [node["sessions"][0]["session_id"] for node in entity_nodes] == [
        "session_coder",
        "session_reviewer",
    ]


def test_token_usage_normalizes_nested_provider_usage() -> None:
    store = MemoryStore()
    recorder = TraceRecorder(store)

    recorder.record(
        CustomTraceEvent(
            event_type="ExternalAgentFinishedEvent",
            session_id="session_codex_usage",
            agent_id="codex",
            summary="done",
            payload={
                "trace_kind": "external_agent",
                "provider": "codex",
                "usage": {
                    "total": {
                        "cached_input_tokens": 10,
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 5,
                        "total_tokens": 125,
                    }
                },
            },
        )
    )

    session = store.get_session("session_codex_usage")
    assert session is not None
    assert session.token_usage.prompt_tokens == 100
    assert session.token_usage.completion_tokens == 25
    assert session.token_usage.total_tokens == 125
    assert session.token_usage.details == {
        "cached_input_tokens": 10,
        "reasoning_output_tokens": 5,
    }


def test_token_usage_accepts_custom_provider_adapter() -> None:
    store = MemoryStore()
    recorder = TraceRecorder(store)
    register_token_usage_adapter(
        "custom_tokens",
        lambda usage: {
            "prompt_tokens": usage["request"],
            "completion_tokens": usage["response"],
            "total_tokens": usage["request"] + usage["response"],
            "details": {"cache_write_tokens": usage["cache_write"]},
        },
    )

    recorder.record(
        CustomTraceEvent(
            event_type="ExternalAgentFinishedEvent",
            session_id="session_custom_usage",
            agent_id="custom",
            summary="done",
            payload={
                "trace_kind": "external_agent",
                "provider": "custom_tokens",
                "usage": {"request": 7, "response": 3, "cache_write": 2},
            },
        )
    )

    session = store.get_session("session_custom_usage")
    assert session is not None
    assert session.token_usage.to_dict() == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
        "details": {"cache_write_tokens": 2},
    }


def test_token_usage_normalizes_claude_cache_details() -> None:
    store = MemoryStore()
    recorder = TraceRecorder(store)

    recorder.record(
        CustomTraceEvent(
            event_type="ExternalAgentFinishedEvent",
            session_id="session_claude_usage",
            agent_id="claude",
            summary="done",
            payload={
                "trace_kind": "external_agent",
                "provider": "claude_code",
                "usage": {
                    "input_tokens": 1584,
                    "cache_creation_input_tokens": 40795,
                    "cache_read_input_tokens": 33281,
                    "output_tokens": 343,
                },
            },
        )
    )

    session = store.get_session("session_claude_usage")
    assert session is not None
    assert session.token_usage.to_dict() == {
        "prompt_tokens": 1584,
        "completion_tokens": 343,
        "total_tokens": 1927,
        "details": {
            "cache_creation_input_tokens": 40795,
            "cache_read_input_tokens": 33281,
        },
    }
