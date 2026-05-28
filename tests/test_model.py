import asyncio

import litellm

from easyagent.config.base import ModelConfig
from easyagent.model.litellm_model import LiteLLMModel


async def main():
    config = ModelConfig.load()
    model = LiteLLMModel(**config.get_model("gemini-2.5-flash"))

    resp = await model.call("hello")
    print(f"Content: {resp.content}")
    print(f"Usage: {resp.usage}")


if __name__ == "__main__":
    asyncio.run(main())

