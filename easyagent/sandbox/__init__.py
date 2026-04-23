"""Sandbox module for isolated code execution."""

from easyagent.sandbox.base import BaseSandbox, ExecResult
from easyagent.sandbox.docker import DockerSandbox
from easyagent.sandbox.local import LocalSandbox

__all__ = [
    "BaseSandbox",
    "ExecResult",
    "DockerSandbox",
    "LocalSandbox",
    "create_sandbox",
]


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
