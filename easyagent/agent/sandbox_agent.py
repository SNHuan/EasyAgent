"""SandboxAgent - ReactAgent with sandbox lifecycle management."""

from typing import Any, Literal

from easyagent.agent.react_agent import ReactAgent
from easyagent.memory.base import BaseMemory
from easyagent.model.base import BaseLLM
from easyagent.sandbox import BaseSandbox, create_sandbox, sandbox_context


class SandboxAgent(ReactAgent):
    """ReactAgent with integrated sandbox lifecycle.

    Sandbox is automatically started before execution and stopped after.
    Tools like bash, write_file, read_file will use this sandbox.
    """

    def __init__(
        self,
        model: BaseLLM,
        system_prompt: str = "",
        tools: list[str] | None = None,
        max_iterations: int = 10,
        memory: BaseMemory | None = None,
        # Sandbox config - either instance or inline params
        sandbox: BaseSandbox | dict | None = None,
        # Inline sandbox params (ignored if sandbox is provided)
        sandbox_type: Literal["local", "docker"] = "local",
        image: str = "python:3.12-slim",
        workdir: str = "/workspace",
        memory_limit: str = "512m",
        cpu_limit: float = 1.0,
        network: bool = True,
    ):
        # Default tools for sandbox agent
        default_tools = ["bash", "write_file", "read_file"]
        if tools:
            tools = list(set(default_tools + tools))
        else:
            tools = default_tools

        super().__init__(model, system_prompt, tools, max_iterations, memory)

        # Build sandbox config from inline params if not provided
        if sandbox is None:
            sandbox = {
                "type": sandbox_type,
                "image": image,
                "workdir": workdir,
                "memory_limit": memory_limit,
                "cpu_limit": cpu_limit,
                "network": network,
            }
        self._sandbox = self._init_sandbox(sandbox)

    def _init_sandbox(self, sandbox: BaseSandbox | dict) -> BaseSandbox:
        """Initialize sandbox from config or instance."""
        if isinstance(sandbox, dict):
            cfg = sandbox.copy()
            sandbox_type = cfg.pop("type", "local")
            return create_sandbox(sandbox_type, **cfg)
        return sandbox

    async def run(self, user_input: str | dict[str, Any] | list[dict[str, Any]]) -> str:
        """Run agent with sandbox lifecycle management."""
        async with self._sandbox:
            with sandbox_context(self._sandbox):
                return await super().run(user_input)
