import pytest

from easyagent import ReactAgent, SlidingWindowContext
from easyagent.memory import InMemoryMemory
from easyagent.model.schema import LLMResponse, ToolCall
from easyagent.tool import ToolManager, register_tool


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def call(self, *args, **kwargs):
        raise NotImplementedError

    async def call_with_history(self, messages, **kwargs):
        if not self._responses:
            raise AssertionError("No more scripted responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def reset_tools():
    ToolManager().reset()
    yield


@pytest.mark.asyncio
async def test_react_agent_runs_tool_loop():
    @register_tool
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
            LLMResponse(content="done <<REACT_COMPLETE>>"),
        ]
    )

    agent = ReactAgent(
        model=llm,
        tools=["echo_tool"],
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=10),
    )
    result = await agent.run("hello")

    assert result == "done"

