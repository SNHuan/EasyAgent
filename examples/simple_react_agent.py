import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import InMemoryMemory, LiteLLMModel, ReactAgent, SlidingWindowContext


async def main() -> None:

    model = LiteLLMModel(model="gpt-4o-mini")
    agent = ReactAgent(
        model=model,
        system_prompt="你是一个简洁、可靠的助手。",
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=12),
        max_iterations=5,
    )

    result = await agent.run("你好")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
