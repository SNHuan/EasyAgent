from __future__ import annotations

from typing import Any

from easyagent.agent.react_agent import ReactAgent
from easyagent.agent.session import AgentSession
from easyagent.sandbox import BaseSandbox, create_sandbox
from easyagent.tool.code.bash import Bash
from easyagent.tool.code.file import ReadFile, WriteFile


class SandboxAgent(ReactAgent):
    """ReactAgent + sandboxed code execution.

    Manages the sandbox lifecycle (start/stop) and registers the
    ``bash``, ``write_file``, and ``read_file`` tools automatically.

    Usage::

        agent = SandboxAgent(
            model=m,
            sandbox=LocalSandbox(),      # or {"type": "local"}
            tools=[my_custom_tool],       # additional tools
        )
    """

    def __init__(
        self,
        model: Any,
        *,
        sandbox: BaseSandbox | dict[str, Any],
        max_iterations: int = 10,
        **kwargs: Any,
    ):
        super().__init__(model, max_iterations=max_iterations, **kwargs)
        self._sandbox = self._build_sandbox(sandbox)
        self.add_tool(
            [
                Bash(),
                WriteFile(),
                ReadFile
            ]
            )

    async def on_session_start(self, session: AgentSession) -> None:
        await super().on_session_start(session)
        await self._sandbox.start()
        session.sandbox = self._sandbox

    async def on_session_end(self, session: AgentSession) -> None:
        try:
            await self._sandbox.stop()
        finally:
            session.sandbox = None
        await super().on_session_end(session)

    @staticmethod
    def _build_sandbox(sandbox: BaseSandbox | dict[str, Any]) -> BaseSandbox:
        if isinstance(sandbox, dict):
            config = sandbox.copy()
            sandbox_type = config.pop("type", "local")
            return create_sandbox(sandbox_type=sandbox_type, **config)
        return sandbox
