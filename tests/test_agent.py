import pytest

from easyagent import ReactAgent
from easyagent.context import SlidingWindowContext
from easyagent.memory import InMemoryMemory
from easyagent.model.schema import LLMResponse, LLMStreamChunk, ToolCall


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

