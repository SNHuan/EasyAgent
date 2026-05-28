from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import EventBus, LiteLLMModel, ReactAgent, SQLiteStore, TraceRecorder


class InspectDashboardTraceDb:
    name = "inspect_dashboard_trace_db"
    type = "function"
    description = "Inspect the current EasyAgent dashboard SQLite trace database."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def init(self) -> None:
        pass

    def execute(self, **_: Any) -> str:
        store = SQLiteStore(self.db_path)
        sessions = store.list_sessions(limit=5)
        signature = store.trace_signature()
        return (
            f"Trace DB: {self.db_path.resolve()}\n"
            f"Sessions: {signature[0]}\n"
            f"Events: {signature[1]}\n"
            f"Latest event row id: {signature[2]}\n"
            f"Recent session ids: {', '.join(session.session_id for session in sessions) or 'none'}"
        )


class DescribeDashboardSurface:
    name = "describe_dashboard_surface"
    type = "function"
    description = "Describe the EasyAgent dashboard panes and the live tracing data they consume."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def init(self) -> None:
        pass

    def execute(self, **_: Any) -> str:
        return (
            "Dashboard panes: session index, timeline, messages, event mix, token usage, "
            "and highlighted event payload. Live updates arrive through /api/traces/stream "
            "and are backed by SQLite trace rows."
        )


async def run_real_stream(db_path: Path, model: str, prompt: str) -> None:
    store = SQLiteStore(db_path)
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(
        model=LiteLLMModel(model),
        system_prompt=(
            "You are an EasyAgent live dashboard demo. Answer in structured markdown with "
            "clear section headings, concise paragraphs, and a small risk checklist. "
            "Make the answer long enough that streaming is visible in a dashboard."
        ),
        tools=[InspectDashboardTraceDb(db_path), DescribeDashboardSurface()],
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
            "First call inspect_dashboard_trace_db, then call describe_dashboard_surface. "
            "Design a practical observability rollout plan for an EasyAgent-based research assistant. "
            "Cover the full lifecycle: session creation, LLM streaming, tool calls, token accounting, "
            "SQLite trace persistence, SSE dashboard updates, failure handling, and release verification. "
            "Include an architecture outline, a step-by-step implementation plan, a debugging workflow, "
            "and five concrete acceptance criteria. Keep it specific to EasyAgent."
        ),
        help="Prompt to stream through the real model.",
    )
    args = parser.parse_args()

    asyncio.run(run_real_stream(Path(args.db), args.model, args.prompt))


if __name__ == "__main__":
    main()
