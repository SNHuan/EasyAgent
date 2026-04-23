from __future__ import annotations

from easyagent.agent.agent import Agent
from easyagent.capability import SandboxCapability, ToolCapability
from easyagent.context.base import BaseContext
from easyagent.loop.react import ReActLoop
from easyagent.memory.base import BaseMemory
from easyagent.model.base import BaseLLM
from easyagent.sandbox import BaseSandbox, create_sandbox


class SandboxAgent(Agent):
    def __init__(
        self,
        model: BaseLLM,
        *,
        sandbox: BaseSandbox | dict,
        system_prompt: str = "",
        max_iterations: int = 10,
        memory: BaseMemory | None = None,
        context: BaseContext | None = None,
        tools: list[str] | None = None,
    ):
        sandbox_instance = self._build_sandbox(sandbox)
        default_tools = ["bash", "write_file", "read_file", *(tools or [])]
        capabilities = [
            SandboxCapability(sandbox_instance),
            ToolCapability(tools=default_tools),
        ]
        super().__init__(
            model=model,
            loop=ReActLoop(max_iterations=max_iterations),
            memory=memory,
            context=context,
            system_prompt=system_prompt,
            capabilities=capabilities,
        )

    @staticmethod
    def _build_sandbox(sandbox: BaseSandbox | dict) -> BaseSandbox:
        if isinstance(sandbox, dict):
            config = sandbox.copy()
            sandbox_type = config.pop("type", "local")
            return create_sandbox(sandbox_type=sandbox_type, **config)
        return sandbox
