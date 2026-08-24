from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from easyagent.external import ExternalRunRequest
from easyagent.external import CodexRunner, ExternalAgentEntity, codex_entity
from easyagent.external.codex import _notification_to_events


def test_codex_entity_wraps_configured_runner() -> None:
    entity = codex_entity(
        "coder",
        cwd=Path("/tmp"),
        model="gpt-5.4",
        sandbox="read_only",
    )

    assert isinstance(entity, ExternalAgentEntity)
    assert entity.id == "coder"
    assert entity.provider == "codex"
    assert isinstance(entity.runner, CodexRunner)
    assert entity.runner.cwd == Path("/tmp").resolve()
    assert entity.runner.model == "gpt-5.4"
    assert entity.runner.sandbox == "read_only"
    assert entity.runner.approval_mode == "deny_all"


@dataclass
class FakePayload:
    delta: str = "hello"
    item_id: str = "item_1"
    thread_id: str = "thread_1"
    turn_id: str = "turn_1"


@dataclass
class FakeNotification:
    method: str
    payload: FakePayload


def test_codex_notification_to_events_maps_streaming_message_delta() -> None:
    events = _notification_to_events(
        FakeNotification(method="item/agentMessage/delta", payload=FakePayload(delta="hello"))
    )

    assert events == [
        {
            "type": "message_delta",
            "role": "assistant",
            "content": "hello",
            "method": "item/agentMessage/delta",
            "item_id": "item_1",
            "raw": {
                "delta": "hello",
                "item_id": "item_1",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
            },
        }
    ]


def test_codex_notification_to_events_maps_command_output_delta() -> None:
    events = _notification_to_events(
        FakeNotification(method="item/commandExecution/outputDelta", payload=FakePayload(delta="stdout"))
    )

    assert events == [
        {
            "type": "tool_result",
            "name": "command",
            "content": "stdout",
            "method": "item/commandExecution/outputDelta",
        }
    ]


@pytest.mark.asyncio
async def test_codex_runner_resumes_an_existing_thread(monkeypatch) -> None:
    import openai_codex

    calls: list[tuple[str, dict[str, object]]] = []

    class ResumeObserved(Exception):
        pass

    class FakeCodex:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def thread_resume(self, thread_id: str, **kwargs):
            calls.append((thread_id, kwargs))
            raise ResumeObserved

    monkeypatch.setattr(openai_codex, "AsyncCodex", FakeCodex)
    runner = CodexRunner(cwd=Path("/tmp"))

    with pytest.raises(ResumeObserved):
        await runner.run(
            ExternalRunRequest(
                prompt="continue",
                session_id="thread-existing",
            )
        )

    assert calls[0][0] == "thread-existing"


@pytest.mark.asyncio
async def test_codex_runner_legacy_metadata_facade(monkeypatch) -> None:
    observed: list[ExternalRunRequest] = []
    runner = CodexRunner(cwd=Path("/tmp"))

    async def fake_run_request(request, *, event_handler=None):
        observed.append(request)
        return object()

    monkeypatch.setattr(runner, "run_request", fake_run_request)

    await runner.run("continue", metadata={"task": "refactor"})

    assert observed[0].metadata == {"task": "refactor"}
