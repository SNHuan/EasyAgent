import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import Agent, InMemoryMemory, LiteLLMModel, ReActLoop, SlidingWindowContext


async def run_session(agent: Agent, prompt: str, label: str) -> None:
    session = agent.create_session()
    result = await agent.run(prompt, session=session)

    print(f"[{label}] result: {result}")
    print(f"[{label}] status: {session.status}")
    print(f"[{label}] iterations: {session.iteration_count}")
    print(f"[{label}] history_count: {len(session.get_all_messages())}")
    print()


async def main() -> None:
    model_name = os.getenv("EA_EXAMPLE_MODEL", "gpt-4o-mini")
    prompt_a = os.getenv("EA_SESSION_PROMPT_A", "我叫 Alice，请记住我的名字。")
    prompt_b = os.getenv("EA_SESSION_PROMPT_B", "我叫 Bob，请记住我的名字。")

    model = LiteLLMModel(model=model_name)
    agent = Agent(
        model=model,
        loop=ReActLoop(max_iterations=5),
        memory=InMemoryMemory(),
        context=SlidingWindowContext(max_messages=12),
        system_prompt="你是一个简洁可靠的助手。",
    )

    await run_session(agent, prompt_a, "session_a")
    await run_session(agent, prompt_b, "session_b")


if __name__ == "__main__":
    asyncio.run(main())
