"""Generate deterministic runtime trace data for the local dashboard.

Usage:
    python examples/16_dashboard_runtime_tree.py --replace
    easyagent dashboard --db apps/dashboard/.easyagent/runtime-tree-demo.db --open
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from easyagent.store import SQLiteStore
from easyagent.tracing import EventTrace, SessionTrace, TokenUsage


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "apps" / "dashboard" / ".easyagent" / "runtime-tree-demo.db"


@dataclass(frozen=True)
class DemoSession:
    run_id: str
    run_title: str
    world: dict[str, Any]
    entity: dict[str, Any]
    task: str
    model: str
    started_offset_minutes: int
    duration_seconds: int
    input_tokens: int
    output_tokens: int
    tool_name: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate dashboard runtime tree demo data.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"Output SQLite DB. Defaults to {DEFAULT_DB}.")
    parser.add_argument("--replace", action="store_true", help="Replace the target DB before writing.")
    args = parser.parse_args()

    db_path = args.db.expanduser().resolve()
    if args.replace:
        remove_sqlite_files(db_path)

    store = SQLiteStore(db_path)
    now = datetime.now().replace(microsecond=0)
    sessions = demo_sessions()
    for index, session in enumerate(sessions):
        write_session(store, session, now=now, index=index)

    print(f"Wrote {len(sessions)} sessions to {db_path}")
    print(f"Open with: easyagent dashboard --db {db_path} --open")
    return 0


def demo_sessions() -> list[DemoSession]:
    release_world = {
        "world_id": "world_release_lab",
        "label": "Release Lab",
        "kind": "planning_world",
        "status": "completed",
        "summary": "Coordinates release planning, risk review, and documentation checks.",
    }
    ops_world = {
        "world_id": "world_ops_room",
        "label": "Ops Room",
        "kind": "monitoring_world",
        "status": "completed",
        "summary": "Runs readiness checks across trace ingestion and dashboard streaming.",
    }
    return [
        DemoSession("runtime_release_20260529", "Runtime: 0.6.2 release planning", release_world, {"entity_id": "planner", "label": "Planner Agent", "kind": "planner"}, "Create the release checklist.", "openai/gemini-3-flash-preview", 132, 18, 812, 436, "read_release_notes"),
        DemoSession("runtime_release_20260529", "Runtime: 0.6.2 release planning", release_world, {"entity_id": "reviewer", "label": "Reviewer Agent", "kind": "critic"}, "Review the dashboard changelog.", "openai/gemini-3-flash-preview", 118, 24, 1054, 512, "scan_changelog"),
        DemoSession("runtime_release_20260529", "Runtime: 0.6.2 release planning", release_world, {"entity_id": "writer", "label": "Docs Agent", "kind": "writer"}, "Draft the release announcement.", "openai/gemini-3-flash-preview", 94, 29, 934, 690, "write_release_draft"),
        DemoSession("runtime_ops_shadow", "Runtime: dashboard live trace inspection", ops_world, {"entity_id": "monitor", "label": "Monitor Agent", "kind": "observer"}, "Inspect live SSE snapshots.", "openai/gemini-3-flash-preview", 46, 15, 676, 318, "inspect_trace_stream"),
        DemoSession("runtime_ops_shadow", "Runtime: dashboard live trace inspection", ops_world, {"entity_id": "debugger", "label": "Debugger Agent", "kind": "debugger"}, "Find timeline grouping issues.", "openai/gemini-3-flash-preview", 31, 21, 744, 284, "inspect_timeline_events"),
    ]


def write_session(store: SQLiteStore, demo: DemoSession, *, now: datetime, index: int) -> None:
    session_id = f"{demo.run_id}_{demo.entity['entity_id']}_{index}_{uuid4().hex[:8]}"
    started = now - timedelta(minutes=demo.started_offset_minutes)
    ended = started + timedelta(seconds=demo.duration_seconds)
    usage = TokenUsage(demo.input_tokens, demo.output_tokens, demo.input_tokens + demo.output_tokens)
    events = events_for_session(demo, session_id=session_id, started=started)
    store.upsert_session(
        SessionTrace(
            session_id=session_id,
            agent_id=str(demo.entity["entity_id"]),
            status="completed",
            started_at=started,
            ended_at=ended,
            event_count=len(events),
            token_usage=usage,
            metadata={
                "run_id": demo.run_id,
                "run_scope": "runtime",
                "run_title": demo.run_title,
                "world": demo.world,
                "entity": demo.entity,
                "version": "0.6.2-demo",
            },
        )
    )
    for event in events:
        store.append_event(event)


def events_for_session(demo: DemoSession, *, session_id: str, started: datetime) -> list[EventTrace]:
    agent_id = str(demo.entity["entity_id"])
    return [
        event(session_id, agent_id, "AgentStartedEvent", started, {"task": demo.task}),
        event(session_id, agent_id, "LLMCalledEvent", started + timedelta(milliseconds=140), {"model": demo.model, "message_count": 2, "messages": [{"role": "user", "content": demo.task}]}),
        event(session_id, agent_id, "ToolCalledEvent", started + timedelta(seconds=2), {"tool_name": demo.tool_name, "arguments": {"run_id": demo.run_id}}),
        event(session_id, agent_id, "ToolResultEvent", started + timedelta(seconds=4), {"tool_name": demo.tool_name, "result": f"{demo.tool_name} completed with 3 findings."}),
        event(session_id, agent_id, "LLMRespondedEvent", started + timedelta(seconds=demo.duration_seconds - 2), {"model": demo.model, "content": f"### Result\n\n- Task: {demo.task}\n- Runtime: {demo.run_id}\n- Entity: {demo.entity['label']}", "usage": {"prompt_tokens": demo.input_tokens, "completion_tokens": demo.output_tokens, "total_tokens": demo.input_tokens + demo.output_tokens}}),
        event(session_id, agent_id, "AgentFinishedEvent", started + timedelta(seconds=demo.duration_seconds), {"output": f"{demo.entity['label']} finished: {demo.task}", "messages": []}),
    ]


def event(session_id: str, agent_id: str, event_type: str, timestamp: datetime, payload: dict[str, Any]) -> EventTrace:
    return EventTrace(f"evt_{uuid4().hex}", session_id, event_type, timestamp, agent_id, payload)


def remove_sqlite_files(path: Path) -> None:
    for candidate in (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm")):
        if candidate.exists():
            candidate.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
