from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import EventBus, LiteLLMModel, ReactAgent, SQLiteStore, TraceRecorder


async def run_real_stream(db_path: Path, model: str, prompt: str) -> None:
    store = SQLiteStore(db_path)
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(
        model=LiteLLMModel(model),
        system_prompt=(
            "You are an EasyAgent live dashboard demo. Answer in concise markdown. "
            "Mention that the response is being streamed and traced into SQLite."
        ),
        max_iterations=4,
    )
    session = agent.create_session()

    print(f"db: {db_path.resolve()}")
    print(f"session: {session.session_id}")
    print("stream:")

    chunks: list[str] = []
    async for chunk in agent.stream(prompt, session=session, event_bus=bus):
        chunks.append(chunk)
        print(chunk, end="", flush=True)

    print("\n\ndone")
    print(f"chunks: {len(chunks)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real streaming EasyAgent session into the dashboard trace DB.")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parents[1] / ".easyagent" / "dashboard-traces.db"),
        help="SQLite trace DB path.",
    )
    parser.add_argument("--model", default="gemini-3-flash-preview", help="LiteLLM model name.")
    parser.add_argument(
        "--prompt",
        default=(
            "Write a short live observability status for EasyAgent. "
            "Use three bullet points: session, streaming, and tracing."
        ),
        help="Prompt to stream through the real model.",
    )
    args = parser.parse_args()

    asyncio.run(run_real_stream(Path(args.db), args.model, args.prompt))


if __name__ == "__main__":
    main()

