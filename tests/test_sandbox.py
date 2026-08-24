import asyncio
from pathlib import Path

import pytest

from easyagent import ConversationWorld, LLMEntity, Runtime, SandboxAgent, SkillAgent, TakeTurns
from easyagent.model.schema import LLMResponse, ToolCall
from easyagent.sandbox.base import ExecResult
from easyagent.sandbox.local import LocalSandbox
from easyagent.skill import SkillManager


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def call(self, *args, **kwargs):
        raise NotImplementedError

    async def call_with_history(self, messages, **kwargs):
        if not self._responses:
            raise AssertionError("No more scripted responses")
        return self._responses.pop(0)


class RecordingSandbox:
    def __init__(self) -> None:
        self.start_count = 0
        self.stop_count = 0
        self.commands: list[str] = []

    async def start(self) -> None:
        self.start_count += 1

    async def stop(self) -> None:
        self.stop_count += 1

    async def exec_command(self, command: str, timeout: int = 30) -> ExecResult:
        self.commands.append(command)
        return ExecResult(exit_code=0, stdout="ok\n", stderr="")

    async def write_file(self, path: str, content: str) -> None:
        raise NotImplementedError

    async def read_file(self, path: str) -> str:
        raise NotImplementedError

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()


@pytest.mark.asyncio
async def test_sandbox_agent_runs_bash_tool():
    llm = FakeLLM(
        [
            LLMResponse(
                content="Use bash",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="bash",
                        arguments={"command": "python -c \"print('ok')\""},
                    )
                ],
            ),
            LLMResponse(content="done"),
        ]
    )

    agent = SandboxAgent(
        model=llm,
        sandbox=LocalSandbox(),
    )
    result = await agent.run("run a command")

    assert result.final_output == "done"


@pytest.mark.asyncio
async def test_sandbox_agent_lifecycle_is_preserved_inside_runtime():
    llm = FakeLLM(
        [
            LLMResponse(
                content="Use bash",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="bash",
                        arguments={"command": "echo ok"},
                    )
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    sandbox = RecordingSandbox()
    entity = LLMEntity("coder", SandboxAgent(model=llm, sandbox=sandbox))
    runtime = Runtime(
        world=ConversationWorld(),
        entities={"coder": entity},
        schedule=TakeTurns(order=["coder"]),
    )

    result = await runtime.run("run a command")

    assert result.last_speech == "done"
    assert sandbox.start_count == 1
    assert sandbox.stop_count == 1
    assert sandbox.commands == ["echo ok"]


@pytest.mark.asyncio
async def test_skill_and_sandbox_capabilities_compose(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\nUse bash when needed.\n",
        encoding="utf-8",
    )
    llm = FakeLLM(
        [
            LLMResponse(
                content="Use bash",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        name="bash",
                        arguments={"command": "echo ok"},
                    )
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    sandbox = RecordingSandbox()
    agent = SkillAgent(
        model=llm,
        skills=["demo"],
        skill_root=tmp_path,
        skill_manager=SkillManager(include_default_dirs=False),
        sandbox=sandbox,
    )
    session = agent.create_session()

    result = await agent.run("run a command", session=session)

    assert result.final_output == "done"
    assert "## Available Skills" in agent.build_system_prompt(session)
    assert sandbox.commands == ["echo ok"]


@pytest.mark.asyncio
async def test_sandbox_factory_creates_session_scoped_instances():
    sandboxes: list[RecordingSandbox] = []

    def create_recording_sandbox() -> RecordingSandbox:
        sandbox = RecordingSandbox()
        sandboxes.append(sandbox)
        return sandbox

    agent = SandboxAgent(
        model=FakeLLM([]),
        sandbox=create_recording_sandbox,
    )
    first = agent.create_session()
    second = agent.create_session()

    await asyncio.gather(
        agent.on_session_start(first),
        agent.on_session_start(second),
    )

    assert first.sandbox is sandboxes[0]
    assert second.sandbox is sandboxes[1]
    assert first.sandbox is not second.sandbox

    await asyncio.gather(
        agent.on_session_end(first),
        agent.on_session_end(second),
    )


@pytest.mark.asyncio
async def test_local_sandbox_default_workdir_is_timestamp_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sandbox = LocalSandbox()

    await sandbox.start()
    workdir = sandbox.workdir

    assert workdir.startswith(str(tmp_path))
    assert workdir.endswith("_workspace")
    assert Path(workdir).is_dir()
