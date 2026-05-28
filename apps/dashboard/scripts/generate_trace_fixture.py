from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import EventBus, LiteLLMModel, ReactAgent, SQLiteStore, TraceRecorder


class SearchRepositories:
    name = "search_github_repositories"
    type = "function"
    description = "Search GitHub repositories for a topic."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def init(self) -> None:
        pass

    def execute(self, query: str) -> str:
        return f"top repositories for {query}: EasyAgent, LiteLLM, OpenTelemetry"


class GetRepositoryDetails:
    name = "get_repository_details"
    type = "function"
    description = "Get repository metadata."
    parameters = {
        "type": "object",
        "properties": {"repo": {"type": "string"}},
        "required": ["repo"],
    }

    def init(self) -> None:
        pass

    def execute(self, repo: str) -> str:
        return f"{repo}: tracing hooks, token usage, SQLite persistence"


async def run_session(
    store: SQLiteStore,
    *,
    prompt: str,
    model: str,
    tools: list[type] | None = None,
    stream: bool = False,
) -> str | None:
    bus = EventBus()
    TraceRecorder(store).attach(bus)
    agent = ReactAgent(
        model=LiteLLMModel(model),
        tools=tools or [],
        max_iterations=4,
    )
    session = agent.create_session()
    try:
        if stream:
            chunks: list[str] = []
            async for chunk in agent.stream(prompt, session=session, event_bus=bus):
                chunks.append(chunk)
            print(f"streamed {len(chunks)} chunks from {session.session_id}")
        else:
            await agent.run(prompt, session=session, event_bus=bus)
        return session.session_id
    except Exception:
        return session.session_id


async def generate_store(db_path: Path) -> SQLiteStore:
    if db_path.exists():
        db_path.unlink()
    store = SQLiteStore(db_path)

    await run_session(
        store,
        prompt=(
            "Use the available tools to inspect EasyAgent. First call "
            "search_github_repositories with query 'AI agent SDK observability', "
            "then call get_repository_details for EasyAgent, then summarize the result "
            "in two concise sentences."
        ),
        model="gemini-3-flash-preview",
        tools=[SearchRepositories, GetRepositoryDetails],
    )

    await run_session(
        store,
        prompt="Explain EasyAgent's tracing store for a dashboard UI in three bullet points.",
        model="gemini-3-flash-preview",
        stream=True,
    )

    await run_session(
        store,
        prompt=(
            "You are reviewing an SDK dashboard. Compare sessions, events, and token usage "
            "as observability concepts in one short paragraph."
        ),
        model="gemini-3-flash-preview",
    )

    await run_session(
        store,
        prompt=(
            "Call get_repository_details for EasyAgent, then produce a short status line "
            "that could appear in an observability dashboard."
        ),
        model="gemini-3-flash-preview",
        tools=[GetRepositoryDetails],
    )

    return store


def export_fixture(store: SQLiteStore, output_path: Path) -> None:
    sessions = store.list_sessions(limit=100)
    hour_buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    exported_sessions: list[dict[str, Any]] = []

    for session in sessions:
        events = store.list_events(session.session_id)
        event_counts = Counter(event.event_type for event in events)
        token_data = session.token_usage.to_dict()
        hour = session.started_at.replace(minute=0, second=0, microsecond=0).isoformat()
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            hour_buckets[hour][key] += int(token_data.get(key, 0))

        exported_sessions.append(
            {
                **session.to_dict(),
                "event_counts": dict(event_counts),
                "events": [event.to_dict() for event in events],
            }
        )

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hourly_token_usage = []
    for offset in range(11, -1, -1):
        hour = (now - timedelta(hours=offset)).isoformat()
        hourly_token_usage.append({"hour": hour, **hour_buckets[hour]})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(),
                "source": "EasyAgent ReactAgent + LiteLLMModel + TraceRecorder + SQLiteStore",
                "sessions": exported_sessions,
                "hourly_token_usage": hourly_token_usage,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main() -> None:
    dashboard_dir = Path(__file__).resolve().parents[1]
    db_path = dashboard_dir / ".easyagent" / "dashboard-traces.db"
    output_path = dashboard_dir / "src" / "data" / "traces.json"
    store = await generate_store(db_path)
    export_fixture(store, output_path)
    print(f"wrote {output_path}")
    print(f"source db {db_path}")


if __name__ == "__main__":
    asyncio.run(main())
