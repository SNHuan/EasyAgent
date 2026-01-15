import asyncio

from easyagent.agent.react_agent import ReactAgent
from easyagent.tool import register_tool
from easyagent.config.base import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel
from easyagent.memory.summary import SummaryMemory


@register_tool
class GetWeather:
    name = "get_weather"
    type = "function"
    description = "Get the weather for a city."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    }

    def init(self) -> None:
        pass

    def execute(self, city: str) -> str:
        return f"The weather in {city} is sunny, 25°C."


@register_tool
class Calculate:
    name = "calculate"
    type = "function"
    description = "Calculate a math expression."
    parameters = {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "Math expression"}},
        "required": ["expression"],
    }

    def init(self) -> None:
        pass

    def execute(self, expression: str) -> str:
        return str(eval(expression))


async def main():
    config = ModelConfig.load()
    model = LiteLLMModel(**config.get_model("gemini-2.5-flash"))


    agent_with_tools = ReactAgent(
        model=model,
        tools=["get_weather", "calculate"],
        system_prompt="You are a helpful assistant. Use tools when needed.",
        memory=SummaryMemory(task_id="test_1", reserve_ratio=0.3),
    )
    result = await agent_with_tools.run("What's the weather in Beijing?")


if __name__ == "__main__":
    asyncio.run(main())

