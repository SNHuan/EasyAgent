"""Dashboard custom hierarchy example.

Run:
  python examples/18_dashboard_custom_groups.py
  easyagent dashboard --db .easyagent/traces.db --open

The dashboard tree will render:
  Custom hierarchy example
    EasyAgent
      Dashboard grouping API
        coder
        reviewer
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import ConversationWorld, EventBus, Runtime, SQLiteStore, TakeTurns, TraceRecorder
from easyagent.dashboard.server import load_trace_payload
from easyagent.external import ExternalAgentEntity, ExternalResult


class GroupedRunner:
    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content

    async def run(
        self,
        prompt: str,
        *,
        metadata: dict[str, Any] | None = None,
        event_handler=None,
    ) -> ExternalResult:
        if event_handler is not None:
            await event_handler(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": f"{self.role} received {len(prompt)} prompt characters.",
                }
            )

        return ExternalResult(
            content=self.content,
            provider="fake_external",
            usage={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            metadata={
                "dashboard_group_path": [
                    {"id": "repo:easyagent", "label": "EasyAgent", "kind": "repo"},
                    {
                        "id": "task:dashboard-grouping-api",
                        "label": "Dashboard grouping API",
                        "kind": "task",
                    },
                ]
            },
        )


def print_tree(nodes: list[dict[str, Any]], indent: int = 0) -> None:
    for node in nodes:
        print(f"{'  ' * indent}- {node['label']} ({node['kind']})")
        sessions = node.get("sessions") if isinstance(node.get("sessions"), list) else []
        for session in sessions:
            print(f"{'  ' * (indent + 1)}- session: {session['agent_id']}")
        children = node.get("children") if isinstance(node.get("children"), list) else []
        print_tree(children, indent + 1)


async def main() -> None:
    trace_db = ROOT / ".easyagent" / "traces.db"
    store = SQLiteStore(trace_db)
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    coder = ExternalAgentEntity(
        "coder",
        runner=GroupedRunner("coder", "Implemented the dashboard grouping projection."),
        provider="fake_external",
    )
    reviewer = ExternalAgentEntity(
        "reviewer",
        runner=GroupedRunner("reviewer", "Reviewed the grouping tree and found no blockers."),
        provider="fake_external",
    )

    runtime = Runtime(
        world=ConversationWorld(),
        entities={"coder": coder, "reviewer": reviewer},
        schedule=TakeTurns(["coder", "reviewer"]),
        bus=bus,
        runtime_id="dashboard_custom_groups_example",
        title="Custom hierarchy example",
    )

    result = await runtime.run("Build and review dashboard custom hierarchy support.")
    payload = load_trace_payload(trace_db)
    run = next(run for run in payload["runs"] if run["run_id"] == "dashboard_custom_groups_example")

    print("last_speech:", result.last_speech)
    print("trace_db:", trace_db)
    print(f"dashboard: easyagent dashboard --db {trace_db} --open")
    print("projected_tree:")
    print_tree(run["tree"])


if __name__ == "__main__":
    asyncio.run(main())
