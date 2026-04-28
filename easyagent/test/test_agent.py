import pytest

from easyagent import ReactAgent
from easyagent.context import SlidingWindowContext
from easyagent.memory import InMemoryMemory
from easyagent.model.schema import LLMResponse, ToolCall


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def call(self, *args, **kwargs):
        raise NotImplementedError

    async def call_with_history(self, messages, **kwargs):
        if not self._responses:
            raise AssertionError("No more scripted responses")
        return self._responses.pop(0)


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
                content="finishing",
                tool_calls=[
                    ToolCall(
                        id="call_2",
                        type="function",
                        name="end",
                        arguments={"data": "done"},
                    )
                ],
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


def test_tool_agent_with_no_extra_tools():
    agent = ReactAgent(
        model=FakeLLM([]),
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=10),
    )
    session = agent.create_session()

    # Only the "end" tool is enabled by default
    assert session.enabled_tools == ["end"]
    schemas = agent.get_tool_schemas(session)
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "end"
