import asyncio

from easyagent.agent import ReactAgent
from easyagent.config.base import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel
from easyagent.tool import DEFAULT_TOOL_MANAGER


async def main():
    config = ModelConfig.load()
    model = LiteLLMModel(**config.get_model("claude-4-5-haiku"))

    agent = ReactAgent(
        model=model,
        tool_manager=DEFAULT_TOOL_MANAGER,
        system_prompt="You are a helpful assistant. Use the search tool to find information.",
        max_iterations=5,
    )

    result = await agent.run("What is the latest version of Python?")
    print(f"Result: {result.final_output}")


if __name__ == "__main__":
    asyncio.run(main())
