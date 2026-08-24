import asyncio
import json
from typing import Any

import pytest

from easyagent import (
    AgentCheckpoint,
    IncompatibleCheckpointError,
    InvalidCheckpointStateError,
    MemoryCheckpointStore,
    ReactAgent,
    SessionNotResumableError,
    SQLiteCheckpointStore,
    UnsupportedCheckpointVersionError,
)
from easyagent.agent import AgentStatus
from easyagent.memory.inmemory import InMemoryMemory
from easyagent.model.schema import LLMResponse, LLMStreamChunk, Message, ToolCall
from easyagent.skill import SkillManager
from easyagent.tool import ToolManager


class FakeLLM:
    async def call_with_history(self, messages, **kwargs):
        return LLMResponse(content="done")


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    async def call_with_history(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        return self._responses.pop(0)


class RecordingCheckpointStore:
    def __init__(self) -> None:
        self.saved: list[AgentCheckpoint] = []

    async def save(self, checkpoint: AgentCheckpoint) -> None:
        self.saved.append(checkpoint)

    async def load(self, session_id: str) -> AgentCheckpoint | None:
        for checkpoint in reversed(self.saved):
            if checkpoint.session_id == session_id:
                return checkpoint
        return None


class FalseyCheckpointStore(RecordingCheckpointStore):
    def __bool__(self) -> bool:
        return False


class FailingCheckpointStore:
    async def save(self, checkpoint: AgentCheckpoint) -> None:
        raise RuntimeError("checkpoint unavailable")

    async def load(self, session_id: str) -> AgentCheckpoint | None:
        return None


class StreamingFakeLLM:
    async def call_with_history_stream(self, messages, **kwargs):
        yield LLMStreamChunk(content="do")
        yield LLMStreamChunk(
            done=True,
            response=LLMResponse(content="done"),
        )


@pytest.mark.asyncio
async def test_agent_run_saves_serializable_checkpoint() -> None:
    store = MemoryCheckpointStore()
    agent = ReactAgent(
        model=FakeLLM(),
        name="writer",
        checkpoint_store=store,
    )
    session = agent.create_session(session_id="checkpoint-session")
    session.metadata["request_id"] = "request-1"

    await agent.run("hello", session=session)

    checkpoint = await store.load("checkpoint-session")
    assert checkpoint is not None
    assert checkpoint.session_id == "checkpoint-session"
    assert checkpoint.agent_identity == agent.checkpoint_identity
    assert checkpoint.agent_name == "writer"
    assert checkpoint.status == "completed"
    assert checkpoint.iteration_count == 1
    assert checkpoint.final_output == "done"
    assert [message["role"] for message in checkpoint.messages] == [
        "user",
        "assistant",
    ]
    assert checkpoint.loop_steps == (
        {"status": "completed", "output": "done"},
    )
    assert checkpoint.metadata == {"request_id": "request-1"}
    assert checkpoint.enabled_tools == ()
    assert checkpoint.loaded_skills == ()
    json.dumps(checkpoint.to_dict())


@pytest.mark.asyncio
async def test_react_run_checkpoints_each_completed_step_boundary() -> None:
    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

        def execute(self, text: str) -> str:
            return text

    store = RecordingCheckpointStore()
    agent = ReactAgent(
        model=ScriptedLLM(
            [
                LLMResponse(
                    content="calling",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            type="function",
                            name="echo",
                            arguments={"text": "hello"},
                        )
                    ],
                ),
                LLMResponse(content="done"),
            ]
        ),
        tools=[EchoTool()],
        checkpoint_store=store,
    )

    result = await agent.run("hello")

    assert result.final_output == "done"
    assert [
        checkpoint.loop_steps[-1]["status"]
        for checkpoint in store.saved
    ] == ["continue", "completed", "completed"]
    assert [checkpoint.status for checkpoint in store.saved] == [
        "running",
        "running",
        "completed",
    ]


@pytest.mark.parametrize(
    "value",
    [object(), float("nan"), float("inf"), float("-inf")],
    ids=["object", "nan", "positive-infinity", "negative-infinity"],
)
@pytest.mark.asyncio
async def test_non_serializable_checkpoint_state_fails_the_run(
    value: Any,
) -> None:
    store = MemoryCheckpointStore()
    agent = ReactAgent(model=FakeLLM(), checkpoint_store=store)
    session = agent.create_session()
    session.metadata["invalid_value"] = value

    with pytest.raises(
        TypeError,
        match="Checkpoint contains non-JSON-serializable state",
    ):
        await agent.run("hello", session=session)

    assert session.status is AgentStatus.FAILED
    assert await store.load(session.session_id) is None


@pytest.mark.asyncio
async def test_stream_saves_the_same_terminal_checkpoint() -> None:
    store = MemoryCheckpointStore()
    agent = ReactAgent(
        model=StreamingFakeLLM(),
        checkpoint_store=store,
    )
    session = agent.create_session(session_id="stream-session")

    chunks = [
        chunk
        async for chunk in agent.stream("hello", session=session)
    ]

    checkpoint = await store.load("stream-session")
    assert chunks == ["do"]
    assert checkpoint is not None
    assert checkpoint.status == "completed"
    assert checkpoint.final_output == "done"
    assert checkpoint.loop_steps == (
        {"status": "completed", "output": "done"},
    )


@pytest.mark.asyncio
async def test_memory_store_load_returns_an_isolated_snapshot() -> None:
    store = MemoryCheckpointStore()
    checkpoint = AgentCheckpoint(
        session_id="isolated-session",
        agent_identity="test/ReactAgent",
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=0,
        metadata={"nested": {"value": "original"}},
    )
    await store.save(checkpoint)

    first = await store.load("isolated-session")
    assert first is not None
    first.metadata["nested"]["value"] = "mutated"

    second = await store.load("isolated-session")
    assert second is not None
    assert second.metadata == {"nested": {"value": "original"}}


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_checkpoint_store_failure_fails_the_run(
    streaming: bool,
) -> None:
    agent = ReactAgent(
        model=StreamingFakeLLM() if streaming else FakeLLM(),
        checkpoint_store=FailingCheckpointStore(),
    )
    session = agent.create_session()

    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        if streaming:
            _ = [
                chunk
                async for chunk in agent.stream("hello", session=session)
            ]
        else:
            await agent.run("hello", session=session)

    assert session.status is AgentStatus.FAILED


@pytest.mark.asyncio
async def test_falsey_session_checkpoint_store_overrides_agent_default() -> None:
    default_store = RecordingCheckpointStore()
    override_store = FalseyCheckpointStore()
    agent = ReactAgent(
        model=FakeLLM(),
        checkpoint_store=default_store,
    )
    session = agent.create_session(checkpoint_store=override_store)

    await agent.run("hello", session=session)

    assert override_store.saved
    assert default_store.saved == []


@pytest.mark.asyncio
async def test_sqlite_checkpoint_store_persists_across_instances(
    tmp_path,
) -> None:
    path = tmp_path / "checkpoints.db"
    agent = ReactAgent(
        model=FakeLLM(),
        checkpoint_store=SQLiteCheckpointStore(path),
    )
    session = agent.create_session(session_id="durable-session")
    session.metadata["request_id"] = "request-1"

    await agent.run("hello", session=session)

    checkpoint = await SQLiteCheckpointStore(path).load(
        "durable-session"
    )
    assert checkpoint is not None
    assert checkpoint.status == "completed"
    assert checkpoint.final_output == "done"
    assert checkpoint.metadata == {"request_id": "request-1"}


@pytest.mark.asyncio
async def test_sqlite_checkpoint_store_initializes_lazily(tmp_path) -> None:
    path = tmp_path / "nested" / "checkpoints.db"
    store = SQLiteCheckpointStore(path)

    assert not path.exists()
    assert await store.load("missing-session") is None
    assert path.exists()


def test_checkpoint_rejects_unsupported_schema_version() -> None:
    payload = AgentCheckpoint(
        session_id="versioned-session",
        agent_identity="test/ReactAgent",
        agent_name="",
        agent_type="ReactAgent",
        status="completed",
        iteration_count=1,
    ).to_dict()
    payload["schema_version"] = 2

    with pytest.raises(
        UnsupportedCheckpointVersionError,
        match="Unsupported checkpoint schema version: 2",
    ):
        AgentCheckpoint.from_dict(payload)


@pytest.mark.asyncio
async def test_sqlite_checkpoint_store_handles_concurrent_sessions(
    tmp_path,
) -> None:
    store = SQLiteCheckpointStore(tmp_path / "checkpoints.db")
    checkpoints = [
        AgentCheckpoint(
            session_id=f"session-{index}",
            agent_identity="test/ReactAgent",
            agent_name="worker",
            agent_type="ReactAgent",
            status="running",
            iteration_count=index,
        )
        for index in range(12)
    ]

    await asyncio.gather(
        *(store.save(checkpoint) for checkpoint in checkpoints)
    )
    loaded = await asyncio.gather(
        *(store.load(checkpoint.session_id) for checkpoint in checkpoints)
    )

    assert [
        checkpoint.session_id
        for checkpoint in loaded
        if checkpoint is not None
    ] == [checkpoint.session_id for checkpoint in checkpoints]


def test_react_agent_accepts_compatible_checkpoint() -> None:
    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            return "ok"

    agent = ReactAgent(
        model=FakeLLM(),
        name="writer",
        tools=[EchoTool()],
    )
    checkpoint = AgentCheckpoint(
        session_id="compatible-session",
        agent_identity=agent.checkpoint_identity,
        agent_name="writer",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        enabled_tools=("echo",),
    )

    report = agent.check_checkpoint(checkpoint)

    assert report.compatible
    assert report.errors == ()


def test_agent_reports_all_checkpoint_identity_mismatches() -> None:
    agent = ReactAgent(model=FakeLLM(), name="editor")
    checkpoint = AgentCheckpoint(
        session_id="mismatched-session",
        agent_identity="legacy/Agent",
        agent_name="writer",
        agent_type="Agent",
        status="running",
        iteration_count=1,
    )

    report = agent.check_checkpoint(checkpoint)

    assert not report.compatible
    assert [issue.code for issue in report.issues] == [
        "agent_identity_mismatch",
        "agent_name_mismatch",
    ]
    assert report.issues[0].checkpoint_value == "legacy/Agent"
    assert report.issues[0].current_value == agent.checkpoint_identity
    assert report.issues[1].checkpoint_value == "writer"
    assert report.issues[1].current_value == "editor"


def test_react_agent_reports_missing_checkpoint_capabilities() -> None:
    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            return "ok"

    agent = ReactAgent(model=FakeLLM(), tools=[EchoTool()])
    checkpoint = AgentCheckpoint(
        session_id="missing-capabilities",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        enabled_tools=("missing-tool", "echo"),
        loaded_skills=("missing-skill",),
    )

    report = agent.check_checkpoint(checkpoint)

    assert not report.compatible
    assert [issue.code for issue in report.issues] == [
        "missing_tools",
        "missing_skills",
    ]
    assert report.issues[0].missing == ("missing-tool",)
    assert report.issues[1].missing == ("missing-skill",)


def test_react_agent_accepts_registered_checkpoint_skill(tmp_path) -> None:
    from easyagent.skill import Skill, SkillManager, SkillMeta

    skill_manager = SkillManager(include_default_dirs=False)
    skill_manager.register(
        Skill(
            SkillMeta(name="demo", description="Demo skill"),
            tmp_path,
        )
    )
    agent = ReactAgent(
        model=FakeLLM(),
        skills=["demo"],
        skill_manager=skill_manager,
    )
    checkpoint = AgentCheckpoint(
        session_id="skill-session",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        loaded_skills=("demo",),
    )

    report = agent.check_checkpoint(checkpoint)

    assert report.compatible
    assert report.errors == ()


def test_checkpoint_preflight_does_not_create_a_session() -> None:
    class NoSessionAgent(ReactAgent):
        def create_session(self, **kwargs):
            raise AssertionError("preflight created a session")

    agent = NoSessionAgent(model=FakeLLM())
    checkpoint = AgentCheckpoint(
        session_id="read-only-preflight",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="NoSessionAgent",
        status="running",
        iteration_count=1,
    )

    report = agent.check_checkpoint(checkpoint)

    assert report.compatible


def test_checkpoint_preflight_does_not_trigger_capability_discovery(
    tmp_path,
    monkeypatch,
) -> None:
    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            return "ok"

    class DiscoveryGuardToolManager(ToolManager):
        def get(self, name: str):
            raise AssertionError("preflight triggered tool discovery")

    class DiscoveryGuardSkillManager(SkillManager):
        def get(self, name: str):
            raise AssertionError("preflight triggered skill discovery")

    def fail_skill_load(path):
        raise AssertionError(
            f"preflight read skill definition at {path}"
        )

    monkeypatch.setattr(
        "easyagent.skill.manager.load_skill_from_dir",
        fail_skill_load,
    )
    tool_manager = DiscoveryGuardToolManager()
    skill_manager = DiscoveryGuardSkillManager(
        include_default_dirs=False,
    )
    skill_manager.add_search_dir(tmp_path / "skills")
    agent = ReactAgent(
        model=FakeLLM(),
        tools=[EchoTool()],
        tool_manager=tool_manager,
        skills=["demo"],
        skill_manager=skill_manager,
    )
    checkpoint = AgentCheckpoint(
        session_id="no-discovery",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        enabled_tools=("echo",),
        loaded_skills=("demo",),
    )

    report = agent.check_checkpoint(checkpoint)

    assert report.compatible
    assert not tool_manager._discovered
    assert skill_manager._skills == {}
    assert skill_manager._discovered_dirs == set()


def test_checkpoint_identity_can_survive_agent_class_rename() -> None:
    class RenamedWriterAgent(ReactAgent):
        pass

    agent = RenamedWriterAgent(
        model=FakeLLM(),
        checkpoint_identity="writer/v1",
    )
    checkpoint = AgentCheckpoint(
        session_id="renamed-agent",
        agent_identity="writer/v1",
        agent_name="",
        agent_type="FormerWriterAgent",
        status="running",
        iteration_count=1,
    )

    report = agent.check_checkpoint(checkpoint)

    assert report.compatible


def test_agent_restores_session_state_without_executing() -> None:
    class NoCallLLM:
        async def call_with_history(self, messages, **kwargs):
            raise AssertionError("restore called the model")

    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            raise AssertionError("restore executed a tool")

    agent = ReactAgent(
        model=NoCallLLM(),
        tools=[EchoTool()],
        skills=["demo"],
        checkpoint_identity="writer/v1",
    )
    checkpoint = AgentCheckpoint(
        session_id="restored-session",
        agent_identity="writer/v1",
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=2,
        final_output="draft",
        messages=(
            {"role": "user", "content": {"text": "hello"}},
            {"role": "assistant", "content": "draft"},
        ),
        loop_steps=(
            {"status": "continue", "output": None},
        ),
        enabled_tools=("echo",),
        loaded_skills=("demo",),
        metadata={"request": {"id": "request-1"}},
        loop_state={"phase": {"name": "drafting"}},
    )

    session = agent.restore_session(checkpoint)

    assert session.session_id == "restored-session"
    assert session.agent is agent
    assert session.status is AgentStatus.RUNNING
    assert session.iteration_count == 2
    assert session.final_output == "draft"
    assert [
        message.model_dump(exclude_none=True)
        for message in session.get_all_messages()
    ] == list(checkpoint.messages)
    assert [
        {"status": step.status.value, "output": step.output}
        for step in session.loop_steps
    ] == list(checkpoint.loop_steps)
    assert session.enabled_tools == ["echo"]
    assert session.loaded_skills == ["demo"]
    assert session.metadata == {"request": {"id": "request-1"}}
    assert session.loop_state == {"phase": {"name": "drafting"}}

    session.get_all_messages()[0].content["text"] = "changed"
    session.metadata["request"]["id"] = "changed"
    session.loop_state["phase"]["name"] = "changed"
    assert checkpoint.messages[0]["content"] == {"text": "hello"}
    assert checkpoint.metadata == {"request": {"id": "request-1"}}
    assert checkpoint.loop_state == {"phase": {"name": "drafting"}}


def test_agent_rejects_incompatible_checkpoint_before_creating_session() -> None:
    class NoSessionAgent(ReactAgent):
        def create_session(self, **kwargs):
            raise AssertionError("incompatible restore created a session")

    agent = NoSessionAgent(
        model=FakeLLM(),
        checkpoint_identity="current/v1",
    )
    checkpoint = AgentCheckpoint(
        session_id="incompatible-restore",
        agent_identity="legacy/v1",
        agent_name="",
        agent_type="FormerAgent",
        status="running",
        iteration_count=1,
    )

    with pytest.raises(IncompatibleCheckpointError) as exc_info:
        agent.restore_session(checkpoint)

    assert [
        issue.code
        for issue in exc_info.value.report.issues
    ] == ["agent_identity_mismatch"]


def test_agent_rejects_invalid_checkpoint_state_before_creating_session() -> None:
    class NoSessionAgent(ReactAgent):
        def create_session(self, **kwargs):
            raise AssertionError("invalid restore created a session")

    agent = NoSessionAgent(model=FakeLLM())
    checkpoint = AgentCheckpoint(
        session_id="invalid-restore",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="NoSessionAgent",
        status="running",
        iteration_count=1,
        messages=(
            {"role": "unknown", "content": "corrupt"},
        ),
    )

    with pytest.raises(
        InvalidCheckpointStateError,
        match="invalid-restore",
    ):
        agent.restore_session(checkpoint)


def test_agent_restore_replaces_seeded_memory_contents() -> None:
    class SeededMemory(InMemoryMemory):
        def __init__(self) -> None:
            super().__init__()
            self.add(Message.user("factory seed"))

        def clone(self) -> InMemoryMemory:
            return SeededMemory()

    agent = ReactAgent(
        model=FakeLLM(),
        memory=SeededMemory(),
    )
    checkpoint = AgentCheckpoint(
        session_id="replace-memory",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        messages=(
            {"role": "user", "content": "checkpoint message"},
        ),
    )

    session = agent.restore_session(checkpoint)

    assert [
        message.content
        for message in session.get_all_messages()
    ] == ["checkpoint message"]


def test_agent_rejects_non_text_checkpoint_step_output() -> None:
    class NoSessionAgent(ReactAgent):
        def create_session(self, **kwargs):
            raise AssertionError("invalid step output created a session")

    agent = NoSessionAgent(model=FakeLLM())
    checkpoint = AgentCheckpoint(
        session_id="invalid-step-output",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="NoSessionAgent",
        status="running",
        iteration_count=1,
        loop_steps=(
            {"status": "continue", "output": {"shared": True}},
        ),
    )

    with pytest.raises(InvalidCheckpointStateError):
        agent.restore_session(checkpoint)


@pytest.mark.parametrize("session_id", ["", "   "])
def test_agent_rejects_checkpoint_with_blank_session_id(
    session_id: str,
) -> None:
    class NoSessionAgent(ReactAgent):
        def create_session(self, **kwargs):
            raise AssertionError("blank session id created a session")

    agent = NoSessionAgent(model=FakeLLM())
    checkpoint = AgentCheckpoint(
        session_id=session_id,
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="NoSessionAgent",
        status="running",
        iteration_count=1,
    )

    with pytest.raises(InvalidCheckpointStateError):
        agent.restore_session(checkpoint)


def test_agent_rejects_non_serializable_checkpoint_during_restore() -> None:
    class NoSessionAgent(ReactAgent):
        def create_session(self, **kwargs):
            raise AssertionError(
                "non-serializable checkpoint created a session"
            )

    agent = NoSessionAgent(model=FakeLLM())
    checkpoint = AgentCheckpoint(
        session_id="non-serializable-restore",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="NoSessionAgent",
        status="running",
        iteration_count=1,
        metadata={"invalid": object()},
    )

    with pytest.raises(InvalidCheckpointStateError):
        agent.restore_session(checkpoint)


@pytest.mark.asyncio
async def test_restored_session_resumes_from_next_react_step() -> None:
    class EchoTool:
        name = "echo"
        type = "function"
        description = "Echo text."
        parameters = {"type": "object", "properties": {}}

        def execute(self) -> str:
            raise AssertionError("resume repeated completed tool work")

    store = RecordingCheckpointStore()
    agent = ReactAgent(
        model=ScriptedLLM([LLMResponse(content="done")]),
        tools=[EchoTool()],
        checkpoint_store=store,
    )
    checkpoint = AgentCheckpoint(
        session_id="resume-react-step",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        messages=(
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "calling",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": '{"text": "hello"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "content": "hello",
                "tool_call_id": "call-1",
            },
        ),
        loop_steps=(
            {"status": "continue", "output": None},
        ),
        enabled_tools=("echo",),
        loop_state={"phase": "after-tool"},
    )
    session = agent.restore_session(checkpoint)

    output = await session.resume()

    assert output == "done"
    assert session.status is AgentStatus.COMPLETED
    assert session.iteration_count == 2
    assert [
        step.status.value
        for step in session.loop_steps
    ] == ["continue", "completed"]
    assert [
        message.role
        for message in session.get_all_messages()
    ] == ["user", "assistant", "tool", "assistant"]
    assert session.loop_state == {"phase": "after-tool"}
    assert store.saved[-1].status == "completed"


@pytest.mark.asyncio
async def test_new_session_cannot_resume() -> None:
    agent = ReactAgent(model=FakeLLM())
    session = agent.create_session()

    with pytest.raises(SessionNotResumableError) as exc_info:
        await session.resume()

    assert exc_info.value.reason == "not_restored"


@pytest.mark.parametrize("status", ["idle", "completed", "failed"])
@pytest.mark.asyncio
async def test_only_running_checkpoint_can_resume(
    status: str,
) -> None:
    class NoCallLLM:
        async def call_with_history(self, messages, **kwargs):
            raise AssertionError("non-running checkpoint called the model")

    agent = ReactAgent(model=NoCallLLM())
    checkpoint = AgentCheckpoint(
        session_id=f"resume-{status}",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status=status,
        iteration_count=1,
    )
    session = agent.restore_session(checkpoint)

    with pytest.raises(SessionNotResumableError) as exc_info:
        await session.resume()

    assert exc_info.value.reason == "checkpoint_not_running"


@pytest.mark.asyncio
async def test_restored_session_resume_is_single_use() -> None:
    agent = ReactAgent(
        model=ScriptedLLM([LLMResponse(content="done")]),
    )
    checkpoint = AgentCheckpoint(
        session_id="single-use-resume",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=0,
        messages=(
            {"role": "user", "content": "hello"},
        ),
    )
    session = agent.restore_session(checkpoint)

    assert await session.resume() == "done"
    with pytest.raises(SessionNotResumableError) as exc_info:
        await session.resume()

    assert exc_info.value.reason == "already_resumed"


@pytest.mark.asyncio
async def test_resume_terminal_step_only_completes_lifecycle() -> None:
    class LifecycleAgent(ReactAgent):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.starts = 0
            self.ends = 0

        async def on_session_start(self, session):
            self.starts += 1
            await super().on_session_start(session)

        async def on_session_end(self, session):
            self.ends += 1
            await super().on_session_end(session)

    class NoCallLLM:
        async def call_with_history(self, messages, **kwargs):
            raise AssertionError("terminal resume called the model")

    store = RecordingCheckpointStore()
    agent = LifecycleAgent(
        model=NoCallLLM(),
        checkpoint_store=store,
    )
    checkpoint = AgentCheckpoint(
        session_id="resume-terminal-step",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="LifecycleAgent",
        status="running",
        iteration_count=2,
        final_output="done",
        messages=(
            {"role": "assistant", "content": "done"},
        ),
        loop_steps=(
            {"status": "continue", "output": None},
            {"status": "completed", "output": "done"},
        ),
    )
    session = agent.restore_session(checkpoint)

    output = await session.resume()

    assert output == "done"
    assert session.status is AgentStatus.COMPLETED
    assert session.iteration_count == 2
    assert len(session.loop_steps) == 2
    assert agent.starts == 1
    assert agent.ends == 1
    assert [
        saved.status
        for saved in store.saved
    ] == ["completed"]


@pytest.mark.asyncio
async def test_failed_resume_must_reload_checkpoint_before_retry() -> None:
    class FailingLLM:
        async def call_with_history(self, messages, **kwargs):
            raise RuntimeError("provider unavailable")

    agent = ReactAgent(model=FailingLLM())
    checkpoint = AgentCheckpoint(
        session_id="failed-resume",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=0,
        messages=(
            {"role": "user", "content": "hello"},
        ),
    )
    session = agent.restore_session(checkpoint)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await session.resume()
    assert session.status is AgentStatus.FAILED

    with pytest.raises(SessionNotResumableError) as exc_info:
        await session.resume()
    assert exc_info.value.reason == "already_resumed"


@pytest.mark.asyncio
async def test_terminal_resume_preserves_explicit_empty_output() -> None:
    store = RecordingCheckpointStore()
    agent = ReactAgent(
        model=FakeLLM(),
        checkpoint_store=store,
    )
    checkpoint = AgentCheckpoint(
        session_id="resume-empty-output",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        final_output="stale output",
        loop_steps=(
            {"status": "completed", "output": ""},
        ),
    )
    session = agent.restore_session(checkpoint)

    output = await session.resume()

    assert output == ""
    assert session.final_output == ""
    assert store.saved[-1].final_output == ""


@pytest.mark.asyncio
async def test_concurrent_resume_allows_only_one_execution() -> None:
    class BlockingLLM:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def call_with_history(self, messages, **kwargs):
            self.started.set()
            await self.release.wait()
            return LLMResponse(content="done")

    model = BlockingLLM()
    agent = ReactAgent(model=model)
    checkpoint = AgentCheckpoint(
        session_id="concurrent-resume",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=0,
        messages=(
            {"role": "user", "content": "hello"},
        ),
    )
    session = agent.restore_session(checkpoint)
    winner = asyncio.create_task(session.resume())
    await model.started.wait()

    with pytest.raises(SessionNotResumableError) as exc_info:
        await session.resume()

    assert exc_info.value.reason == "already_resumed"
    model.release.set()
    assert await winner == "done"


@pytest.mark.asyncio
async def test_restore_defers_sandbox_lifecycle_until_resume() -> None:
    class RecordingSandbox:
        def __init__(self) -> None:
            self.start_count = 0
            self.stop_count = 0

        async def start(self) -> None:
            self.start_count += 1

        async def stop(self) -> None:
            self.stop_count += 1

        async def exec_command(self, command: str, timeout: int = 30):
            raise AssertionError("terminal resume executed sandbox command")

        async def write_file(self, path: str, content: str) -> None:
            raise AssertionError("terminal resume wrote a sandbox file")

        async def read_file(self, path: str) -> str:
            raise AssertionError("terminal resume read a sandbox file")

        async def __aenter__(self):
            await self.start()
            return self

        async def __aexit__(self, *args) -> None:
            await self.stop()

    sandbox = RecordingSandbox()
    agent = ReactAgent(
        model=FakeLLM(),
        sandbox=sandbox,
    )
    checkpoint = AgentCheckpoint(
        session_id="resume-sandbox-lifecycle",
        agent_identity=agent.checkpoint_identity,
        agent_name="",
        agent_type="ReactAgent",
        status="running",
        iteration_count=1,
        final_output="done",
        loop_steps=(
            {"status": "completed", "output": "done"},
        ),
    )

    session = agent.restore_session(checkpoint)

    assert sandbox.start_count == 0
    assert sandbox.stop_count == 0
    assert session.sandbox is None
    assert session.resources == {}

    assert await session.resume() == "done"
    assert sandbox.start_count == 1
    assert sandbox.stop_count == 1
    assert session.sandbox is None
    assert session.resources == {}
