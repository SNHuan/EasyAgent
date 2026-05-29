"""Generate real runtime traces with gemini-3-flash-preview.

Usage:
    python examples/17_real_runtime_tracing.py --replace
    easyagent dashboard --db apps/dashboard/.easyagent/real-runtime-traces.db --open
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import (  # noqa: E402
    ConversationWorld,
    EventBus,
    LLMEntity,
    LiteLLMModel,
    MaxTicks,
    PipelineWorld,
    ReactAgent,
    RoundRobin,
    Runtime,
    SQLiteStore,
    TakeTurns,
    TraceRecorder,
)
from easyagent.events import MessageEvent, RuntimeFinishedEvent, RuntimeStartedEvent  # noqa: E402


DEFAULT_DB = ROOT / "apps" / "dashboard" / ".easyagent" / "real-runtime-traces.db"
DEFAULT_MODEL = "gemini-3-flash-preview"


def make_entity(model: LiteLLMModel, name: str, prompt: str) -> LLMEntity:
    return LLMEntity(name, ReactAgent(model=model, name=name, system_prompt=prompt, max_iterations=2))


def make_bus(store: SQLiteStore, *, verbose: bool) -> EventBus:
    bus = EventBus()
    TraceRecorder(store).attach(bus)
    if verbose:
        bus.subscribe(RuntimeStartedEvent, lambda event: print(f"\n[runtime:start] {event.run_id}"))
        bus.subscribe(RuntimeFinishedEvent, lambda event: print(f"[runtime:finish] {event.run_id} {event.status}"))
        bus.subscribe(MessageEvent, lambda event: print(f"[{event.sender}] {event.content[:180]}"))
    return bus


async def run_release_runtime(model: LiteLLMModel, bus: EventBus, suffix: str) -> None:
    entities = {
        "planner": make_entity(model, "planner", "你是 EasyAgent 发布规划员。输出最多 4 条 bullet。"),
        "reviewer": make_entity(model, "reviewer", "你是严格的工程 reviewer。指出风险和遗漏，最多 4 条 bullet。"),
        "writer": make_entity(model, "writer", "你是发布说明撰写员。写一段面向 SDK 用户的 release note，120 字以内。"),
    }
    runtime = Runtime(
        world=PipelineWorld(order=list(entities)),
        entities=entities,
        schedule=TakeTurns(order=list(entities)),
        bus=bus,
        runtime_id=f"runtime_real_release_{suffix}",
        title="Runtime: real release planning",
        metadata={"example": "17_real_runtime_tracing", "scenario": "release_planning"},
    )
    result = await runtime.run("EasyAgent 新增 runtime/world/entity/session 层级 observability。请协作完成发布说明。")
    print("\nrelease final:")
    print(result.last_speech or "(no final speech)")


async def run_dashboard_runtime(model: LiteLLMModel, bus: EventBus, suffix: str) -> None:
    entities = {
        "observer": make_entity(model, "observer", "你是 dashboard 观测员。描述要看哪些 trace 信号，最多 3 条。"),
        "debugger": make_entity(model, "debugger", "你是调试工程师。基于前文给出排查步骤，最多 4 条。"),
    }
    runtime = Runtime(
        world=ConversationWorld(channel="incident-room"),
        entities=entities,
        schedule=MaxTicks(inner=RoundRobin(ids=list(entities)), n=3),
        bus=bus,
        runtime_id=f"runtime_real_dashboard_{suffix}",
        title="Runtime: real dashboard incident review",
        metadata={"example": "17_real_runtime_tracing", "scenario": "dashboard_incident"},
    )
    result = await runtime.run("用户反馈 dashboard 中 session tree 的选中状态异常。请协作定位运行时事件。")
    print("\ndashboard speeches:")
    for entity_id, speech in result.speeches():
        print(f"- {entity_id}: {speech}")


async def async_main(args: argparse.Namespace) -> None:
    db_path = args.db.expanduser().resolve()
    if args.replace:
        remove_sqlite_files(db_path)
    store = SQLiteStore(db_path)
    bus = make_bus(store, verbose=args.verbose)
    model = LiteLLMModel(args.model)
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    await run_release_runtime(model, bus, suffix)
    await run_dashboard_runtime(model, bus, suffix)
    print(f"\ntrace_db: {db_path}")
    print(f"open: easyagent dashboard --db {db_path} --open")


def remove_sqlite_files(path: Path) -> None:
    for candidate in (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm")):
        if candidate.exists():
            candidate.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate real EasyAgent runtime traces with an LLM model.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"Output SQLite DB. Defaults to {DEFAULT_DB}.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model name from config.yaml. Defaults to {DEFAULT_MODEL}.")
    parser.add_argument("--replace", action="store_true", help="Replace the target DB before running.")
    parser.add_argument("--quiet", dest="verbose", action="store_false", help="Do not print live runtime messages.")
    parser.set_defaults(verbose=True)
    return parser.parse_args()


def main() -> int:
    asyncio.run(async_main(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
