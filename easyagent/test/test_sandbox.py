import asyncio

from easyagent import SandboxAgent
from easyagent.config import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel


async def main():
    config = ModelConfig.load()
    model = LiteLLMModel(**config.get_model("gemini-3-flash-preview"))

    # 方式3: 使用 docker sandbox
    agent = SandboxAgent(
        model=model,
        sandbox={
            "type": "docker",
            "image": "python:3.12-slim",
            "memory_limit": "512m",
            "network": True,  # 是否允许网络访问
        },
    )

    result = await agent.run("写一个计算斐波那契数列的程序并运行")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())