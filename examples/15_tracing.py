"""第 15 层：Tracing + Store。

TraceRecorder 订阅 EventBus，把一次 agent session 的生命周期、LLM 调用、
工具调用和 token 统计写入 Store。这里用 SQLiteStore，适合作为后续
dashboard 的本地数据源。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyagent import EventBus, LiteLLMModel, ReactAgent, SQLiteStore, TraceRecorder


class GetProjectName:
    name = "get_project_name"
    type = "function"
    description = "返回当前项目名。"
    parameters = {"type": "object", "properties": {}}

    def init(self) -> None:
        pass

    def execute(self) -> str:
        return "EasyAgent"


async def main() -> None:
    trace_db = ROOT / ".easyagent" / "traces.db"
    store = SQLiteStore(trace_db)
    bus = EventBus()
    TraceRecorder(store).attach(bus)

    agent = ReactAgent(
        model=LiteLLMModel("gpt-4o-mini"),
        tools=[GetProjectName],
        max_iterations=3,
    )

    result = await agent.run(
        "调用 get_project_name，然后用一句话介绍这个项目。",
        event_bus=bus,
    )

    session_id = result.session.session_id
    session_trace = store.get_session(session_id)
    events = store.list_events(session_id)

    print("final:", result.final_output)
    print("trace_db:", trace_db)
    if session_trace:
        print("status:", session_trace.status)
        print("tokens:", session_trace.token_usage.to_dict())
    print("events:", [event.event_type for event in events])


if __name__ == "__main__":
    asyncio.run(main())
