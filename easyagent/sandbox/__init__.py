"""Sandbox module for isolated code execution."""

from contextvars import ContextVar

from easyagent.sandbox.base import BaseSandbox, ExecResult
from easyagent.sandbox.impl import DockerSandbox, LocalSandbox

__all__ = [
    "BaseSandbox",
    "ExecResult",
    "DockerSandbox",
    "LocalSandbox",
    "create_sandbox",
    "get_sandbox",
    "sandbox_context",
]

# Context variable for current sandbox (supports concurrent agents)
_sandbox_var: ContextVar[BaseSandbox | None] = ContextVar("sandbox", default=None)


def create_sandbox(
    sandbox_type: str = "local",
    **kwargs,
) -> BaseSandbox:
    """Factory function to create sandbox by type."""
    if sandbox_type == "docker":
        return DockerSandbox(**kwargs)
    elif sandbox_type == "local":
        return LocalSandbox(**kwargs)
    else:
        raise ValueError(f"Unknown sandbox type: {sandbox_type}")


def get_sandbox() -> BaseSandbox | None:
    """Get current sandbox from context (used by tools)."""
    return _sandbox_var.get()


class sandbox_context:
    """Context manager to set sandbox for current execution context."""

    def __init__(self, sandbox: BaseSandbox | None):
        self._sandbox = sandbox
        self._token = None

    def __enter__(self):
        self._token = _sandbox_var.set(self._sandbox)
        return self

    def __exit__(self, *args):
        if self._token is not None:
            _sandbox_var.reset(self._token)
