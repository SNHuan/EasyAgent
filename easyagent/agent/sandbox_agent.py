from __future__ import annotations

from collections.abc import Callable
from typing import Any

from easyagent.agent.react_agent import ReactAgent
from easyagent.sandbox import BaseSandbox


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
        sandbox: BaseSandbox | dict[str, Any] | Callable[[], BaseSandbox],
        max_iterations: int = 10,
        **kwargs: Any,
    ):
        super().__init__(
            model,
            sandbox=sandbox,
            max_iterations=max_iterations,
            **kwargs,
        )
