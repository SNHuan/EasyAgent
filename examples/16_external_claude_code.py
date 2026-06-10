"""Minimal real Claude Code SDK entity example.

Run:
  pip install -e ".[external]"
  python examples/16_external_claude_code.py
"""

from __future__ import annotations

import asyncio


import asyncio
from pathlib import Path

from easyagent import ConversationWorld, EventBus, Runtime, SQLiteStore, TakeTurns, TraceRecorder
from easyagent.external import claude_code_entity
ROOT = Path(__file__).resolve().parents[1]

async def main() -> None:
    trace_db = ROOT / ".easyagent" / "traces.db"
    store = SQLiteStore(trace_db)
    bus = EventBus()
    TraceRecorder(store).attach(bus)
    claude = claude_code_entity(
        "claude",
        max_turns=3,
        allowed_tools=["Read", "Glob", "Grep"],
    )

    runtime = Runtime(
        world=ConversationWorld(),
        entities={"claude": claude},
        schedule=TakeTurns(["claude"]),
        bus=bus,
        runtime_id="external_claude_code_example",
        title="External Claude Code example",
    )

    result = await runtime.run("How do you think this project architectural design?")
    print(result.last_speech)

架构
if __name__ == "__main__":
    asyncio.run(main())
