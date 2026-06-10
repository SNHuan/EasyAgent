"""Minimal real Codex SDK entity example.

Run:
  pip install -e ".[external]"
  python examples/17_external_codex.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from easyagent import ConversationWorld, EventBus, Runtime, SQLiteStore, TakeTurns, TraceRecorder
from easyagent.external import codex_entity

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    trace_db = ROOT / ".easyagent" / "traces.db"
    store = SQLiteStore(trace_db)
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    codex = codex_entity(
        "codex",
        sandbox="read_only",
        approval_mode="deny_all",
    )

    runtime = Runtime(
        world=ConversationWorld(),
        entities={"codex": codex},
        schedule=TakeTurns(["codex"]),
        bus=bus,
        runtime_id="external_codex_example",
        title="External Codex example",
    )

    result = await runtime.run("Read README.md and summarize EasyAgent in two bullets.")
    print(result.last_speech)
    print("trace_db:", trace_db)
    print(f"dashboard: easyagent dashboard --db {trace_db} --open")


if __name__ == "__main__":
    asyncio.run(main())
