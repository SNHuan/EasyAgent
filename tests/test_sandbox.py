from pathlib import Path

import pytest

from easyagent import SandboxAgent
from easyagent.model.schema import LLMResponse, ToolCall
from easyagent.sandbox.local import LocalSandbox


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def call(self, *args, **kwargs):
        raise NotImplementedError

    async def call_with_history(self, messages, **kwargs):
        if not self._responses:
            raise AssertionError("No more scripted responses")
        return self._responses.pop(0)


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
async def test_local_sandbox_default_workdir_is_timestamp_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sandbox = LocalSandbox()

    await sandbox.start()
    workdir = sandbox.workdir

    assert workdir.startswith(str(tmp_path))
    assert workdir.endswith("_workspace")
    assert Path(workdir).is_dir()
