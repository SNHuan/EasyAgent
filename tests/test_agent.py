import pytest

from easyagent import ReactAgent
from easyagent.context import SlidingWindowContext
from easyagent.memory import InMemoryMemory
from easyagent.model.schema import LLMResponse, LLMStreamChunk, Message, ToolCall


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def call(self, *args, **kwargs):
        raise NotImplementedError

    async def call_with_history(self, messages, **kwargs):
        if not self._responses:
            raise AssertionError("No more scripted responses")
        return self._responses.pop(0)


class StreamingFakeLLM(FakeLLM):
    def __init__(self, responses, chunks):
        super().__init__(responses)
        self._chunks = list(chunks)

    async def call_with_history_stream(self, messages, **kwargs):
        response = self._responses.pop(0)
        for chunk in self._chunks.pop(0):
            yield LLMStreamChunk(content=chunk)
        yield LLMStreamChunk(done=True, response=response)


@pytest.mark.asyncio
async def test_tool_agent_runs_tool_loop():
    class EchoTool:
        name = "echo_tool"
        type = "function"
        description = "Echo a string."
        parameters = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

        def init(self) -> None:
            pass

        def execute(self, text: str, **kwargs) -> str:
            return f"echo:{text}"

    llm = FakeLLM(
        [
            LLMResponse(
                content="Calling tool",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="echo_tool",
                        arguments={"text": "hi"},
                    )
                ],
            ),
            LLMResponse(
                content="done",
            ),
        ]
    )

    agent = ReactAgent(
        model=llm,
        tools=[EchoTool()],
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=10),
    )
    result = await agent.run("hello")

    assert result.final_output == "done"


@pytest.mark.asyncio
async def test_react_agent_stops_on_plain_text_by_default():
    llm = FakeLLM([LLMResponse(content="plain final")])
    agent = ReactAgent(
        model=llm,
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=10),
    )

    result = await agent.run("hello")

    assert result.final_output == "plain final"
    assert result.iteration_count == 1
    assert result.enabled_tools == []


def test_tool_agent_with_no_extra_tools():
    agent = ReactAgent(
        model=FakeLLM([]),
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=10),
    )
    session = agent.create_session()

    assert session.enabled_tools == []
    assert agent.get_tool_schemas(session) == []
    assert "writing the final answer directly" in agent.build_system_prompt(session)


@pytest.mark.asyncio
async def test_agent_stream_yields_chunks_and_updates_session():
    llm = StreamingFakeLLM(
        [LLMResponse(content="hello world")],
        [["hello", " ", "world"]],
    )
    agent = ReactAgent(model=llm)
    session = agent.create_session()

    chunks = [chunk async for chunk in agent.stream("say hi", session=session)]

    assert chunks == ["hello", " ", "world"]
    assert session.final_output == "hello world"
    assert session.get_all_messages()[-1].content == "hello world"


@pytest.mark.asyncio
async def test_react_agent_stream_preserves_message_input():
    llm = StreamingFakeLLM(
        [LLMResponse(content="done")],
        [["done"]],
    )
    agent = ReactAgent(model=llm)
    session = agent.create_session()
    message = Message.user("hello", name="planner")

    chunks = [chunk async for chunk in agent.stream(message, session=session)]

    assert chunks == ["done"]
    assert session.get_all_messages()[0] == message


@pytest.mark.asyncio
async def test_session_start_failure_marks_failed_and_runs_cleanup():
    from easyagent import Agent, EventBus
    from easyagent.agent import AgentStatus
    from easyagent.events import AgentFailedEvent

    class StartFailingAgent(Agent):
        def __init__(self):
            super().__init__(FakeLLM([]))
            self.cleanup_count = 0

        async def on_session_start(self, session):
            raise RuntimeError("setup failed")

        async def on_session_end(self, session):
            self.cleanup_count += 1

    agent = StartFailingAgent()
    session = agent.create_session()
    bus = EventBus()

    with pytest.raises(RuntimeError, match="setup failed"):
        await session.run("hello", event_bus=bus)

    assert session.status is AgentStatus.FAILED
    assert agent.cleanup_count == 1
    assert bus.history(AgentFailedEvent)[0].error == "setup failed"


@pytest.mark.asyncio
async def test_session_cleanup_failure_marks_failed():
    from easyagent import Agent, EventBus
    from easyagent.agent import AgentStatus
    from easyagent.events import AgentFailedEvent, AgentFinishedEvent

    class CleanupFailingAgent(Agent):
        async def on_session_end(self, session):
            raise RuntimeError("cleanup failed")

    agent = CleanupFailingAgent(FakeLLM([LLMResponse(content="done")]))
    session = agent.create_session()
    bus = EventBus()

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await session.run("hello", event_bus=bus)

    assert session.status is AgentStatus.FAILED
    assert bus.history(AgentFinishedEvent) == []
    assert bus.history(AgentFailedEvent)[0].error == "cleanup failed"


@pytest.mark.asyncio
async def test_closing_stream_early_marks_session_failed_and_runs_cleanup():
    from easyagent.agent import AgentStatus

    class CleanupTrackingAgent(ReactAgent):
        def __init__(self, model):
            super().__init__(model)
            self.cleanup_count = 0

        async def on_session_end(self, session):
            self.cleanup_count += 1
            await super().on_session_end(session)

    llm = StreamingFakeLLM(
        [LLMResponse(content="hello world")],
        [["hello", "world"]],
    )
    agent = CleanupTrackingAgent(llm)
    session = agent.create_session()
    stream = agent.stream("say hi", session=session)

    assert await anext(stream) == "hello"
    await stream.aclose()

    assert session.status is AgentStatus.FAILED
    assert agent.cleanup_count == 1


@pytest.mark.asyncio
async def test_context_tool_receives_explicit_session_context():
    from easyagent.tool import Tool, ToolContext, ToolResult

    observed_contexts: list[ToolContext] = []

    class InspectContextTool(Tool):
        context_aware = True
        name = "inspect_context"
        type = "function"
        description = "Inspect the active tool context."
        parameters = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }

        async def execute(
            self,
            arguments: dict,
            context: ToolContext,
        ) -> ToolResult:
            observed_contexts.append(context)
            return ToolResult(content=f"{context.session_id}:{arguments['value']}")

    llm = FakeLLM(
        [
            LLMResponse(
                content="Calling tool",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="inspect_context",
                        arguments={"value": "ok"},
                    )
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    agent = ReactAgent(model=llm, tools=[InspectContextTool()])
    session = agent.create_session(session_id="session-1")

    result = await agent.run("inspect", session=session)

    assert result.final_output == "done"
    assert observed_contexts == [ToolContext(session=session)]
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert [message.content for message in tool_messages] == ["session-1:ok"]


@pytest.mark.asyncio
async def test_structured_tool_result_is_preserved_in_events():
    from easyagent import EventBus, Tool, ToolContext, ToolResult
    from easyagent.events import ToolResultEvent

    class FailingContextTool(Tool):
        context_aware = True
        name = "failing_context"
        type = "function"
        description = "Return a structured failure."
        parameters = {"type": "object", "properties": {}}

        async def execute(
            self,
            arguments: dict,
            context: ToolContext,
        ) -> ToolResult:
            return ToolResult(
                content="failed",
                is_error=True,
                metadata={"code": "denied"},
            )

    llm = FakeLLM(
        [
            LLMResponse(
                content="Calling tool",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="failing_context",
                        arguments={},
                    )
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    bus = EventBus()
    agent = ReactAgent(model=llm, tools=[FailingContextTool()])

    await agent.run("inspect", event_bus=bus)

    result_event = bus.history(ToolResultEvent)[0]
    assert result_event.result == "failed"
    assert result_event.is_error is True
    assert result_event.metadata == {"code": "denied"}


@pytest.mark.asyncio
async def test_legacy_tool_subclass_uses_legacy_adapter():
    from easyagent.tool import Tool, ToolContext, ToolManager

    class LegacyTool(Tool):
        name = "legacy"
        type = "function"
        description = "Legacy keyword-based tool."
        parameters = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        }

        async def execute(self, value: str, **kwargs) -> str:
            return f"legacy:{value}:{kwargs['session'].session_id}"

    agent = ReactAgent(model=FakeLLM([]))
    session = agent.create_session(session_id="legacy-session")
    manager = ToolManager(discover_builtin=False)
    manager.register(LegacyTool())

    result = await manager.execute(
        "legacy",
        {"value": "ok"},
        ToolContext(session=session),
    )

    assert result.content == "legacy:ok:legacy-session"


@pytest.mark.asyncio
async def test_context_tool_contract_uses_explicit_marker_not_parameter_names():
    from easyagent.tool import Tool, ToolContext, ToolManager

    class ExplicitContextTool(Tool):
        context_aware = True
        name = "explicit_context"
        type = "function"
        description = "Context tool with concise parameter names."
        parameters = {"type": "object", "properties": {}}

        async def execute(self, args, ctx):
            return f"{ctx.session_id}:{args['value']}"

    class AmbiguousLegacyTool(Tool):
        name = "ambiguous_legacy"
        type = "function"
        description = "Legacy tool whose business arguments resemble the new API."
        parameters = {"type": "object", "properties": {}}

        async def execute(self, arguments: str, context: str):
            return f"{arguments}:{context}"

    agent = ReactAgent(model=FakeLLM([]))
    session = agent.create_session(session_id="explicit-session")
    manager = ToolManager(discover_builtin=False)
    manager.register(ExplicitContextTool())
    manager.register(AmbiguousLegacyTool())

    context_result = await manager.execute(
        "explicit_context",
        {"value": "ok"},
        ToolContext(session=session),
    )
    legacy_result = await manager.execute(
        "ambiguous_legacy",
        {"arguments": "left", "context": "right"},
        ToolContext(session=session),
    )

    assert context_result.content == "explicit-session:ok"
    assert legacy_result.content == "left:right"


@pytest.mark.asyncio
async def test_before_tool_hook_failure_blocks_tool_execution():
    from easyagent import BeforeToolCallHook, HookManager

    executed: list[str] = []

    class RecordingTool:
        name = "recording"
        type = "function"
        description = "Record execution."
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            executed.append("called")
            return "done"

    hooks = HookManager()

    async def fail_before_tool(hook: BeforeToolCallHook):
        raise RuntimeError("policy unavailable")

    hooks.on(BeforeToolCallHook, fail_before_tool)
    llm = FakeLLM(
        [
            LLMResponse(
                content="Calling tool",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="recording",
                        arguments={},
                    )
                ],
            ),
        ]
    )
    agent = ReactAgent(model=llm, tools=[RecordingTool()], hooks=hooks)

    with pytest.raises(RuntimeError, match="policy unavailable"):
        await agent.run("run")

    assert executed == []


@pytest.mark.asyncio
async def test_before_tool_hook_can_block_with_structured_tool_result():
    from easyagent import BeforeToolCallHook, BeforeToolCallResult, HookManager

    executed: list[str] = []

    class RecordingTool:
        name = "recording"
        type = "function"
        description = "Record execution."
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            executed.append("called")
            return "done"

    hooks = HookManager()
    hooks.on(
        BeforeToolCallHook,
        lambda hook: BeforeToolCallResult(
            block=True,
            reason="blocked by policy",
        ),
    )
    llm = FakeLLM(
        [
            LLMResponse(
                content="Calling tool",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="recording",
                        arguments={},
                    )
                ],
            ),
            LLMResponse(content="handled"),
        ]
    )
    agent = ReactAgent(model=llm, tools=[RecordingTool()], hooks=hooks)

    result = await agent.run("run")

    assert result.final_output == "handled"
    assert executed == []
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert [message.content for message in tool_messages] == ["blocked by policy"]


@pytest.mark.asyncio
async def test_tool_hooks_compose_argument_and_result_transforms_in_order():
    from easyagent import (
        AfterToolCallHook,
        BeforeToolCallHook,
        BeforeToolCallResult,
        HookManager,
        ToolResult,
    )

    executed: list[str] = []
    observed_arguments: list[dict] = []

    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }

        def execute(self, text: str):
            executed.append(text)
            return f"echo:{text}"

    hooks = HookManager()
    hooks.on(
        BeforeToolCallHook,
        lambda hook: BeforeToolCallResult(arguments={"text": "rewritten"}),
    )

    def observe_rewritten_arguments(hook: BeforeToolCallHook):
        observed_arguments.append(dict(hook.arguments))

    hooks.on(BeforeToolCallHook, observe_rewritten_arguments)
    hooks.on(
        AfterToolCallHook,
        lambda hook: ToolResult(
            content=f"audited:{hook.result.content}",
            metadata={"audited": True},
        ),
    )
    llm = FakeLLM(
        [
            LLMResponse(
                content="Calling tool",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="echo",
                        arguments={"text": "original"},
                    )
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    agent = ReactAgent(model=llm, tools=[EchoTool()], hooks=hooks)

    result = await agent.run("run")

    assert executed == ["rewritten"]
    assert observed_arguments == [{"text": "rewritten"}]
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert [message.content for message in tool_messages] == [
        "audited:echo:rewritten"
    ]


@pytest.mark.asyncio
async def test_session_stop_request_is_control_not_an_event() -> None:
    from easyagent import Tool, ToolContext, ToolResult

    class StopTool(Tool):
        context_aware = True
        name = "stop"
        type = "function"
        description = "Stop the active session."
        parameters = {"type": "object", "properties": {}}

        async def execute(
            self,
            arguments: dict,
            context: ToolContext,
        ) -> ToolResult:
            context.session.request_stop(
                reason="handoff complete",
                data="finished",
            )
            return ToolResult(content="stopping")

    llm = FakeLLM(
        [
            LLMResponse(
                content="Stopping",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="stop",
                        arguments={},
                    )
                ],
            ),
        ]
    )
    agent = ReactAgent(model=llm, tools=[StopTool()])

    result = await agent.run("run")

    assert result.final_output == "finished"
    assert result.session.metadata["stop_reason"] == "handoff complete"


@pytest.mark.asyncio
async def test_stop_requested_during_setup_survives_run_initialization() -> None:
    import asyncio

    from easyagent import Agent

    setup_started = asyncio.Event()
    release_setup = asyncio.Event()

    class SetupWaitingAgent(Agent):
        async def on_session_start(self, session) -> None:
            setup_started.set()
            await release_setup.wait()

    llm = FakeLLM([LLMResponse(content="should not run")])
    agent = SetupWaitingAgent(llm)
    session = agent.create_session()
    task = asyncio.create_task(agent.run("run", session=session))
    await setup_started.wait()

    session.request_stop(reason="cancelled", data="stopped")
    release_setup.set()
    result = await task

    assert result.final_output == "stopped"
    assert len(llm._responses) == 1


@pytest.mark.asyncio
async def test_stop_requested_during_llm_call_wins_at_next_boundary() -> None:
    import asyncio

    llm_started = asyncio.Event()
    release_llm = asyncio.Event()

    class WaitingLLM:
        async def call_with_history(self, messages, **kwargs):
            llm_started.set()
            await release_llm.wait()
            return LLMResponse(content="model result")

    agent = ReactAgent(model=WaitingLLM())
    session = agent.create_session()
    task = asyncio.create_task(agent.run("run", session=session))
    await llm_started.wait()

    session.request_stop(reason="cancelled", data="stopped")
    release_llm.set()
    result = await task

    assert result.final_output == "stopped"


@pytest.mark.asyncio
async def test_unavailable_tool_results_still_pass_through_hooks() -> None:
    from easyagent import (
        AfterToolCallHook,
        BeforeToolCallHook,
        HookManager,
        ToolResult,
    )

    observed: list[str] = []
    hooks = HookManager()
    hooks.on(
        BeforeToolCallHook,
        lambda hook: observed.append(f"before:{hook.tool_name}"),
    )
    hooks.on(
        AfterToolCallHook,
        lambda hook: (
            observed.append(f"after:{hook.result.is_error}")
            or ToolResult(content="audited unavailable", is_error=True)
        ),
    )
    agent = ReactAgent(model=FakeLLM([]), hooks=hooks)
    session = agent.create_session()

    result = await agent.execute_tool_call(session, "missing", {})

    assert result == "audited unavailable"
    assert observed == ["before:missing", "after:True"]


@pytest.mark.asyncio
async def test_streaming_tool_calls_use_the_same_hooks() -> None:
    from easyagent import BeforeToolCallHook, BeforeToolCallResult, HookManager

    executed: list[str] = []

    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }

        def execute(self, text: str) -> str:
            executed.append(text)
            return text

    hooks = HookManager()
    hooks.on(
        BeforeToolCallHook,
        lambda hook: BeforeToolCallResult(arguments={"text": "rewritten"}),
    )
    llm = StreamingFakeLLM(
        [
            LLMResponse(
                content="calling",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="echo",
                        arguments={"text": "original"},
                    )
                ],
            ),
            LLMResponse(content="done"),
        ],
        [["calling"], ["done"]],
    )
    agent = ReactAgent(model=llm, tools=[EchoTool()], hooks=hooks)

    chunks = [chunk async for chunk in agent.stream("run")]

    assert chunks == ["calling", "done"]
    assert executed == ["rewritten"]


@pytest.mark.asyncio
async def test_publishing_stop_event_does_not_control_a_session() -> None:
    from easyagent import EventBus
    from easyagent.events import StopEvent

    agent = ReactAgent(model=FakeLLM([LLMResponse(content="done")]))
    session = agent.create_session(session_id="session-1")
    bus = EventBus()

    await bus.publish(
        StopEvent(
            session_id=session.session_id,
            reason="observer notification",
            data="must not become output",
        )
    )
    result = await agent.run("run", session=session, event_bus=bus)

    assert result.final_output == "done"


@pytest.mark.asyncio
async def test_run_and_stream_share_react_transition_semantics() -> None:
    from easyagent import (
        AfterToolCallHook,
        BeforeToolCallHook,
        BeforeToolCallResult,
        EventBus,
        HookManager,
        ToolResult,
    )
    from easyagent.events import LLMStreamChunkEvent

    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }

        def __init__(self, observed: list[str]) -> None:
            self._observed = observed

        def execute(self, text: str) -> str:
            self._observed.append(text)
            return f"echo:{text}"

    def make_hooks(observed: list[str]) -> HookManager:
        hooks = HookManager()
        hooks.on(
            BeforeToolCallHook,
            lambda hook: (
                observed.append(f"before:{hook.arguments['text']}")
                or BeforeToolCallResult(arguments={"text": "rewritten"})
            ),
        )
        hooks.on(
            AfterToolCallHook,
            lambda hook: (
                observed.append(f"after:{hook.arguments['text']}")
                or ToolResult(content=f"wrapped:{hook.result.content}")
            ),
        )
        return hooks

    tool_response = LLMResponse(
        content="calling",
        tool_calls=[
            ToolCall(
                id="call_1",
                type="function",
                name="echo",
                arguments={"text": "original"},
            )
        ],
    )
    final_response = LLMResponse(content="done")

    run_tool_calls: list[str] = []
    run_hook_calls: list[str] = []
    run_bus = EventBus()
    run_agent = ReactAgent(
        model=FakeLLM([tool_response, final_response]),
        tools=[EchoTool(run_tool_calls)],
        hooks=make_hooks(run_hook_calls),
    )
    run_result = await run_agent.run("run", event_bus=run_bus)

    stream_tool_calls: list[str] = []
    stream_hook_calls: list[str] = []
    stream_bus = EventBus()
    stream_agent = ReactAgent(
        model=StreamingFakeLLM(
            [tool_response, final_response],
            [["calling"], ["done"]],
        ),
        tools=[EchoTool(stream_tool_calls)],
        hooks=make_hooks(stream_hook_calls),
    )
    stream_session = stream_agent.create_session()
    stream_chunks = [
        chunk
        async for chunk in stream_agent.stream(
            "run",
            session=stream_session,
            event_bus=stream_bus,
        )
    ]

    def event_names(bus: EventBus) -> list[str]:
        return [
            type(event).__name__
            for event in bus.history()
            if not isinstance(event, LLMStreamChunkEvent)
        ]

    assert stream_chunks == ["calling", "done"]
    assert stream_session.final_output == run_result.final_output == "done"
    assert stream_tool_calls == run_tool_calls == ["rewritten"]
    assert stream_hook_calls == run_hook_calls == [
        "before:original",
        "after:rewritten",
    ]
    assert [
        (message.role, message.content)
        for message in stream_session.get_all_messages()
    ] == [
        (message.role, message.content)
        for message in run_result.messages
    ]
    assert [
        step.status for step in stream_session.loop_steps
    ] == [
        step.status for step in run_result.loop_steps
    ]
    assert event_names(stream_bus) == event_names(run_bus)


@pytest.mark.asyncio
async def test_run_engine_respects_agent_tool_schema_extension_point() -> None:
    observed_kwargs: list[dict] = []

    class CapturingLLM:
        async def call_with_history(self, messages, **kwargs):
            observed_kwargs.append(kwargs)
            return LLMResponse(content="done")

    class HiddenToolsAgent(ReactAgent):
        def get_tool_schemas(self, session) -> list[dict]:
            return []

    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            return "echo"

    agent = HiddenToolsAgent(model=CapturingLLM(), tools=[EchoTool()])

    result = await agent.run("run")

    assert result.final_output == "done"
    assert observed_kwargs == [{}]


@pytest.mark.asyncio
async def test_streaming_run_honors_stop_requested_by_tool() -> None:
    from easyagent import Tool, ToolContext, ToolResult
    from easyagent.agent import StepStatus

    class StopTool(Tool):
        context_aware = True
        name = "stop"
        type = "function"
        description = "Stop the active run."
        parameters = {"type": "object", "properties": {}}

        async def execute(
            self,
            arguments: dict,
            context: ToolContext,
        ) -> ToolResult:
            context.session.request_stop(
                reason="complete",
                data="finished",
            )
            return ToolResult(content="stopping")

    response = LLMResponse(
        content="calling",
        tool_calls=[
            ToolCall(
                id="call_1",
                type="function",
                name="stop",
                arguments={},
            )
        ],
    )
    agent = ReactAgent(
        model=StreamingFakeLLM([response], [["calling"]]),
        tools=[StopTool()],
    )
    session = agent.create_session()

    chunks = [
        chunk
        async for chunk in agent.stream("run", session=session)
    ]

    assert chunks == ["calling"]
    assert session.final_output == "finished"
    assert [step.status for step in session.loop_steps] == [
        StepStatus.EARLY_EXIT
    ]


@pytest.mark.asyncio
async def test_run_engine_resolves_dynamic_model_when_step_starts() -> None:
    first_model = FakeLLM([LLMResponse(content="first")])
    second_model = FakeLLM([LLMResponse(content="second")])

    class RoutedAgent(ReactAgent):
        def __init__(self) -> None:
            super().__init__(model=first_model)
            self.active_model = first_model

        @property
        def default_model(self):
            return self.active_model

    agent = RoutedAgent()
    agent.active_model = second_model

    result = await agent.run("run")

    assert result.final_output == "second"
    assert len(first_model._responses) == 1


@pytest.mark.asyncio
async def test_run_engine_respects_execute_tool_call_extension_point() -> None:
    observed: list[tuple[str, dict]] = []

    class VirtualToolAgent(ReactAgent):
        def get_tool_schemas(self, session) -> list[dict]:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "virtual",
                        "description": "Virtual tool.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]

        async def execute_tool_call(
            self,
            session,
            name: str,
            arguments: dict,
        ) -> str:
            observed.append((name, arguments))
            return "virtual result"

    agent = VirtualToolAgent(
        model=FakeLLM(
            [
                LLMResponse(
                    content="calling",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            type="function",
                            name="virtual",
                            arguments={"value": "ok"},
                        )
                    ],
                ),
                LLMResponse(content="done"),
            ]
        )
    )

    result = await agent.run("run")

    assert observed == [("virtual", {"value": "ok"})]
    assert [
        message.content
        for message in result.messages
        if message.role == "tool"
    ] == ["virtual result"]


@pytest.mark.asyncio
async def test_streaming_run_falls_back_when_provider_omits_final_response() -> None:
    class MissingFinalResponseLLM:
        def __init__(self) -> None:
            self.fallback_calls = 0

        async def call_with_history_stream(self, messages, **kwargs):
            yield LLMStreamChunk(content="partial")

        async def call_with_history(self, messages, **kwargs):
            self.fallback_calls += 1
            return LLMResponse(content="recovered")

    llm = MissingFinalResponseLLM()
    agent = ReactAgent(model=llm)
    session = agent.create_session()

    chunks = [
        chunk
        async for chunk in agent.stream("run", session=session)
    ]

    assert chunks == ["partial"]
    assert session.final_output == "recovered"
    assert llm.fallback_calls == 1


@pytest.mark.asyncio
async def test_run_and_stream_share_max_iteration_semantics() -> None:
    from easyagent.agent import StepStatus

    class NoopTool:
        name = "noop"
        type = "function"
        description = "Do nothing."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            return "ok"

    response = LLMResponse(
        content="calling",
        tool_calls=[
            ToolCall(
                id="call_1",
                type="function",
                name="noop",
                arguments={},
            )
        ],
    )
    run_agent = ReactAgent(
        model=FakeLLM([response]),
        tools=[NoopTool()],
        max_iterations=1,
    )
    run_result = await run_agent.run("run")

    stream_agent = ReactAgent(
        model=StreamingFakeLLM([response], [["calling"]]),
        tools=[NoopTool()],
        max_iterations=1,
    )
    stream_session = stream_agent.create_session()
    chunks = [
        chunk
        async for chunk in stream_agent.stream(
            "run",
            session=stream_session,
        )
    ]

    assert chunks == ["calling"]
    assert [
        step.status for step in run_result.loop_steps
    ] == [
        StepStatus.CONTINUE,
        StepStatus.MAX_ITERATIONS,
    ]
    assert [
        step.status for step in stream_session.loop_steps
    ] == [
        step.status for step in run_result.loop_steps
    ]


@pytest.mark.asyncio
async def test_run_engine_is_safe_across_concurrent_sessions() -> None:
    import asyncio

    class ConcurrentLLM:
        def __init__(self) -> None:
            self.started = 0
            self.both_started = asyncio.Event()

        async def _respond(self, messages) -> LLMResponse:
            self.started += 1
            if self.started == 2:
                self.both_started.set()
            await self.both_started.wait()
            user_content = next(
                message["content"]
                for message in reversed(messages)
                if message["role"] == "user"
            )
            return LLMResponse(content=f"reply:{user_content}")

        async def call_with_history(self, messages, **kwargs):
            return await self._respond(messages)

        async def call_with_history_stream(self, messages, **kwargs):
            response = await self._respond(messages)
            yield LLMStreamChunk(content=response.content)
            yield LLMStreamChunk(done=True, response=response)

    llm = ConcurrentLLM()
    agent = ReactAgent(model=llm)
    run_session = agent.create_session()
    stream_session = agent.create_session()

    run_task = asyncio.create_task(
        agent.run("alpha", session=run_session)
    )

    async def collect_stream() -> list[str]:
        return [
            chunk
            async for chunk in agent.stream(
                "beta",
                session=stream_session,
            )
        ]

    stream_task = asyncio.create_task(collect_stream())
    run_result, stream_chunks = await asyncio.gather(run_task, stream_task)

    assert run_result.final_output == "reply:alpha"
    assert stream_chunks == ["reply:beta"]
    assert stream_session.final_output == "reply:beta"


@pytest.mark.asyncio
async def test_stopped_run_does_not_resolve_dynamic_model() -> None:
    class UnavailableModelAgent(ReactAgent):
        @property
        def default_model(self):
            raise RuntimeError("model route unavailable")

    agent = UnavailableModelAgent(model=FakeLLM([]))
    session = agent.create_session()
    session.request_stop(reason="cancelled", data="stopped")

    result = await agent.run("run", session=session)

    assert result.final_output == "stopped"


@pytest.mark.asyncio
async def test_maxed_run_does_not_resolve_dynamic_model_again() -> None:
    from easyagent.agent import StepStatus

    class NoopTool:
        name = "noop"
        type = "function"
        description = "Do nothing."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            return "ok"

    model = FakeLLM(
        [
            LLMResponse(
                content="calling",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="noop",
                        arguments={},
                    )
                ],
            )
        ]
    )

    class OneShotModelAgent(ReactAgent):
        model_resolutions = 0

        @property
        def default_model(self):
            self.model_resolutions += 1
            if self.model_resolutions > 1:
                raise RuntimeError("model resolved after max iterations")
            return model

    agent = OneShotModelAgent(
        model=model,
        tools=[NoopTool()],
        max_iterations=1,
    )

    result = await agent.run("run")

    assert agent.model_resolutions == 1
    assert result.loop_steps[-1].status is StepStatus.MAX_ITERATIONS


@pytest.mark.asyncio
async def test_execute_tool_call_super_delegation_runs_hooks_once() -> None:
    from easyagent import (
        AfterToolCallHook,
        BeforeToolCallHook,
        HookManager,
    )

    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }

        def execute(self, text: str) -> str:
            return text

    class DecoratingAgent(ReactAgent):
        async def execute_tool_call(
            self,
            session,
            name: str,
            arguments: dict,
        ) -> str:
            result = await super().execute_tool_call(
                session,
                name,
                arguments,
            )
            return f"decorated:{result}"

    observed: list[str] = []
    hooks = HookManager()
    hooks.on(
        BeforeToolCallHook,
        lambda hook: observed.append("before"),
    )
    hooks.on(
        AfterToolCallHook,
        lambda hook: observed.append("after"),
    )
    agent = DecoratingAgent(
        model=FakeLLM(
            [
                LLMResponse(
                    content="calling",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            type="function",
                            name="echo",
                            arguments={"text": "ok"},
                        )
                    ],
                ),
                LLMResponse(content="done"),
            ]
        ),
        tools=[EchoTool()],
        hooks=hooks,
    )

    result = await agent.run("run")

    assert observed == ["before", "after"]
    assert [
        message.content
        for message in result.messages
        if message.role == "tool"
    ] == ["decorated:ok"]
