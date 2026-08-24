from __future__ import annotations

import pytest

from easyagent import ChatMessage, ConversationWorld, EventBus, MemoryStore, Runtime, TakeTurns, TraceRecorder
from easyagent.core.types import Action, MessagesSlice, Perception, SetState, Speak
from easyagent.external import ExternalAgentEntity, ExternalResult, ExternalRunRequest


class RecordingRunner:
    def __init__(self, result: str | ExternalResult) -> None:
        self.result = result
        self.prompts: list[str] = []
        self.metadata: list[dict[str, object]] = []

    async def run(self, prompt: str, *, metadata: dict[str, object] | None = None) -> str | ExternalResult:
        self.prompts.append(prompt)
        self.metadata.append(dict(metadata or {}))
        return self.result


class FailingRunner:
    async def run(self, prompt: str, *, metadata: dict[str, object] | None = None) -> str:
        raise RuntimeError("external failed")


class StreamingRunner:
    async def run(
        self,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
        event_handler=None,
    ) -> ExternalResult:
        assert event_handler is not None
        await event_handler({"type": "message_delta", "role": "assistant", "content": "hel"})
        await event_handler({"type": "message_delta", "role": "assistant", "content": "lo"})
        return ExternalResult(
            content="hello",
            provider="fake",
            events=[{"type": "message", "role": "assistant", "content": "hello"}],
        )


class StatefulRunner:
    def __init__(self) -> None:
        self.requests: list[ExternalRunRequest] = []

    async def run_request(
        self,
        call,
        *,
        event_handler=None,
    ) -> ExternalResult:
        self.requests.append(call)
        return ExternalResult(
            content="done",
            provider="fake",
            session_id=call.session_id or "provider-session",
        )


class RequestNamedLegacyRunner:
    def __init__(self) -> None:
        self.values: list[str] = []

    async def run(self, request: str) -> str:
        self.values.append(request)
        return "done"


@pytest.mark.asyncio
async def test_external_agent_entity_renders_visible_messages_and_speaks_result() -> None:
    runner = RecordingRunner("implemented")
    entity = ExternalAgentEntity("coder", runner=runner, provider="fake")
    perception = Perception(
        entity_id="coder",
        tick=0,
        slices=(
            MessagesSlice(
                messages=(
                    ChatMessage(sender="user", content="build it"),
                    ChatMessage(sender="planner", content="use small steps"),
                )
            ),
        ),
    )

    action = await entity.act(perception)

    assert action == Speak(content="implemented")
    assert runner.prompts == ["[user] build it\n[planner] use small steps"]
    assert runner.metadata[0]["entity_id"] == "coder"
    assert runner.metadata[0]["provider"] == "fake"


@pytest.mark.asyncio
async def test_external_agent_entity_resumes_the_provider_session() -> None:
    runner = StatefulRunner()
    entity = ExternalAgentEntity("coder", runner=runner, provider="fake")
    perception = Perception(
        entity_id="coder",
        tick=0,
        slices=(
            MessagesSlice(
                messages=(ChatMessage(sender="user", content="first"),)
            ),
        ),
    )

    await entity.act(perception)
    await entity.act(perception)

    assert [request.session_id for request in runner.requests] == [
        None,
        "provider-session",
    ]


@pytest.mark.asyncio
async def test_external_agent_entity_does_not_guess_protocol_from_parameter_name() -> None:
    runner = RequestNamedLegacyRunner()
    entity = ExternalAgentEntity("coder", runner=runner, provider="fake")
    perception = Perception(
        entity_id="coder",
        tick=0,
        slices=(
            MessagesSlice(
                messages=(ChatMessage(sender="user", content="build it"),)
            ),
        ),
    )

    await entity.act(perception)

    assert runner.values == ["[user] build it"]


@pytest.mark.asyncio
async def test_external_agent_entity_accepts_structured_result_and_custom_output_mapper() -> None:
    runner = RecordingRunner(
        ExternalResult(
            content="done",
            provider="fake",
            session_id="provider-session",
            usage={"input_tokens": 3, "output_tokens": 2},
            metadata={"artifact": "patch.diff"},
        )
    )
    entity = ExternalAgentEntity(
        "coder",
        runner=runner,
        output_mapper=lambda result: SetState("artifact", result.metadata["artifact"]),
    )

    action = await entity.act(Perception(entity_id="coder", tick=0))

    assert action == SetState("artifact", "patch.diff")
    assert entity.provider_session_id == "provider-session"


@pytest.mark.asyncio
async def test_external_agent_entity_emits_dashboard_trace_events_inside_runtime() -> None:
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    runner = RecordingRunner(
        ExternalResult(
            content="implemented",
            provider="fake",
            session_id="provider-session",
            usage={"input_tokens": 4, "output_tokens": 6},
        )
    )
    entity = ExternalAgentEntity("coder", runner=runner, provider="fake")
    runtime = Runtime(
        world=ConversationWorld(),
        entities={"coder": entity},
        schedule=TakeTurns(order=["coder"]),
        bus=bus,
        runtime_id="runtime_external",
        title="External runtime",
    )

    result = await runtime.run("build it")

    assert result.last_speech == "implemented"
    sessions = {
        session.session_id: session
        for session in store.list_sessions()
        if session.session_id != "runtime_external"
    }
    assert len(sessions) == 1
    external_session = next(iter(sessions.values()))
    assert external_session.agent_id == "coder"
    assert external_session.metadata["run_id"] == "runtime_external"
    assert external_session.metadata["run_scope"] == "runtime"
    assert external_session.metadata["entity"]["entity_id"] == "coder"
    assert external_session.metadata["provider"] == "fake"
    assert external_session.metadata["provider_session_id"] == "provider-session"
    assert external_session.token_usage.prompt_tokens == 4
    assert external_session.token_usage.completion_tokens == 6

    events = store.list_events(external_session.session_id)
    assert [event.event_type for event in events] == [
        "ExternalAgentStartedEvent",
        "ExternalAgentFinishedEvent",
    ]
    assert events[-1].payload["content"] == "implemented"
    assert events[-1].payload["display"]["surface"] == "messages"
    assert events[-1].payload["display"]["content"] == "implemented"


@pytest.mark.asyncio
async def test_external_agent_entity_promotes_dashboard_group_path_from_result_metadata() -> None:
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    runner = RecordingRunner(
        ExternalResult(
            content="implemented",
            provider="fake",
            metadata={
                "dashboard_group_path": [
                    {"id": "repo:easyagent", "label": "EasyAgent", "kind": "repo"},
                    {"id": "task:dashboard-tree", "label": "Dashboard Tree", "kind": "task"},
                ]
            },
        )
    )
    entity = ExternalAgentEntity("coder", runner=runner, provider="fake")
    runtime = Runtime(
        world=ConversationWorld(),
        entities={"coder": entity},
        schedule=TakeTurns(order=["coder"]),
        bus=bus,
        runtime_id="runtime_external_grouped",
    )

    await runtime.run("build it")

    external_session = next(
        session
        for session in store.list_sessions()
        if session.session_id != "runtime_external_grouped"
    )
    assert external_session.metadata["dashboard_group_path"] == [
        {"id": "repo:easyagent", "label": "EasyAgent", "kind": "repo"},
        {"id": "task:dashboard-tree", "label": "Dashboard Tree", "kind": "task"},
    ]


@pytest.mark.asyncio
async def test_external_agent_entity_emits_failed_trace_event() -> None:
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    entity = ExternalAgentEntity("coder", runner=FailingRunner(), provider="fake")
    runtime = Runtime(
        world=ConversationWorld(),
        entities={"coder": entity},
        schedule=TakeTurns(order=["coder"]),
        bus=bus,
        runtime_id="runtime_failed_external",
    )

    with pytest.raises(RuntimeError, match="external failed"):
        await runtime.run("build it")

    external_sessions = [
        session
        for session in store.list_sessions()
        if session.session_id != "runtime_failed_external"
    ]
    assert len(external_sessions) == 1
    assert external_sessions[0].status == "failed"
    events = store.list_events(external_sessions[0].session_id)
    assert [event.event_type for event in events] == [
        "ExternalAgentStartedEvent",
        "ExternalAgentFailedEvent",
    ]
    assert events[-1].payload["error"] == "external failed"


@pytest.mark.asyncio
async def test_external_agent_entity_publishes_default_provider_event_stream() -> None:
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    runner = RecordingRunner(
        ExternalResult(
            content="done",
            provider="fake",
            events=[
                {"type": "message", "role": "assistant", "content": "Inspecting README."},
                {"type": "tool_call", "name": "Read", "arguments": {"file": "README.md"}},
                {"type": "tool_result", "name": "Read", "content": "README contents"},
                {"type": "raw_event", "summary": "provider-specific event"},
            ],
        )
    )
    entity = ExternalAgentEntity("coder", runner=runner, provider="fake")
    runtime = Runtime(
        world=ConversationWorld(),
        entities={"coder": entity},
        schedule=TakeTurns(order=["coder"]),
        bus=bus,
        runtime_id="runtime_external_events",
    )

    await runtime.run("build it")

    external_session = next(
        session
        for session in store.list_sessions()
        if session.session_id != "runtime_external_events"
    )
    events = store.list_events(external_session.session_id)
    assert [event.event_type for event in events] == [
        "ExternalAgentStartedEvent",
        "ExternalAgentMessageEvent",
        "ExternalAgentToolCallEvent",
        "ExternalAgentToolResultEvent",
        "ExternalAgentProviderEvent",
        "ExternalAgentFinishedEvent",
    ]
    assert events[1].payload["display"]["surface"] == "messages"
    assert events[1].payload["display"]["content"] == "Inspecting README."
    assert events[2].payload["tool_name"] == "Read"
    assert events[3].payload["tool_name"] == "Read"


@pytest.mark.asyncio
async def test_external_agent_entity_streams_provider_events_via_event_handler() -> None:
    store = MemoryStore()
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    entity = ExternalAgentEntity("coder", runner=StreamingRunner(), provider="fake")
    runtime = Runtime(
        world=ConversationWorld(),
        entities={"coder": entity},
        schedule=TakeTurns(order=["coder"]),
        bus=bus,
        runtime_id="runtime_external_streaming",
    )

    await runtime.run("build it")

    external_session = next(
        session
        for session in store.list_sessions()
        if session.session_id != "runtime_external_streaming"
    )
    events = store.list_events(external_session.session_id)
    assert [event.event_type for event in events] == [
        "ExternalAgentStartedEvent",
        "ExternalAgentMessageDeltaEvent",
        "ExternalAgentMessageDeltaEvent",
        "ExternalAgentMessageEvent",
        "ExternalAgentFinishedEvent",
    ]
    assert [event.payload["sequence"] for event in events[1:4]] == [1, 2, 3]
    assert events[1].payload["display"]["surface"] == "hidden"
    assert events[2].payload["display"]["surface"] == "hidden"
    assert events[3].payload["display"]["surface"] == "messages"
    assert events[3].payload["display"]["content"] == "hello"
