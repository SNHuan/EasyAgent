from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from easyagent.external import ClaudeCodeRunner, ExternalAgentEntity, claude_code_entity


def test_claude_code_entity_wraps_configured_runner() -> None:
    entity = claude_code_entity(
        "coder",
        cwd=Path("/tmp"),
        max_turns=2,
        allowed_tools=["Read"],
        model="claude-sonnet-4-5-20250929",
    )

    assert isinstance(entity, ExternalAgentEntity)
    assert entity.id == "coder"
    assert entity.provider == "claude_code"
    assert isinstance(entity.runner, ClaudeCodeRunner)
    assert entity.runner.cwd == Path("/tmp").resolve()
    assert entity.runner.max_turns == 2
    assert entity.runner.allowed_tools == ["Read"]
    assert entity.runner.model == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_claude_code_runner_streams_provider_events(monkeypatch) -> None:
    @dataclass
    class TextBlock:
        text: str

    @dataclass
    class ToolUseBlock:
        id: str
        name: str
        input: dict[str, str]

    @dataclass
    class ToolResultBlock:
        tool_use_id: str
        content: str
        is_error: bool | None = None

    @dataclass
    class AssistantMessage:
        content: list[object]
        model: str = "claude-test"

    @dataclass
    class UserMessage:
        content: list[object] | str

    @dataclass
    class ResultMessage:
        subtype: str
        session_id: str
        result: str
        usage: dict[str, int]
        is_error: bool = False
        num_turns: int = 1
        duration_ms: int = 10
        duration_api_ms: int = 9
        total_cost_usd: float | None = None

    class ClaudeCodeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def query(*, prompt, options):
        yield AssistantMessage([TextBlock("Reading README."), ToolUseBlock("tool_1", "Read", {"file_path": "README.md"})])
        yield UserMessage([ToolResultBlock("tool_1", "file contents")])
        yield AssistantMessage([TextBlock("Final summary")])
        yield ResultMessage("success", "provider_session", "Final summary", {"input_tokens": 4, "output_tokens": 2})

    fake_sdk = types.SimpleNamespace(
        AssistantMessage=AssistantMessage,
        ClaudeCodeOptions=ClaudeCodeOptions,
        ResultMessage=ResultMessage,
        TextBlock=TextBlock,
        ToolResultBlock=ToolResultBlock,
        ToolUseBlock=ToolUseBlock,
        UserMessage=UserMessage,
        query=query,
    )
    monkeypatch.setitem(sys.modules, "claude_code_sdk", fake_sdk)

    runner = ClaudeCodeRunner(cwd=Path("/tmp"), allowed_tools=["Read"])
    streamed_events: list[dict[str, object]] = []

    async def event_handler(event: dict[str, object]) -> None:
        streamed_events.append(event)

    result = await runner.run(
        "summarize",
        event_handler=event_handler,
    )

    assert result.content == "Final summary"
    assert result.session_id == "provider_session"
    assert result.usage == {"input_tokens": 4, "output_tokens": 2}
    assert result.events == []
    assert [event["type"] for event in streamed_events] == [
        "message",
        "tool_call",
        "tool_result",
        "message",
        "result",
    ]
    assert streamed_events[2]["content"] == "file contents"
