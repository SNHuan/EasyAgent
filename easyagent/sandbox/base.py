"""Sandbox base protocol and types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ExecResult:
    """Result of command execution in sandbox."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        """Combined output for tool response."""
        if self.success:
            return self.stdout.strip() or "(no output)"
        return f"Exit code: {self.exit_code}\n{self.stderr.strip() or self.stdout.strip()}"


@runtime_checkable
class BaseSandbox(Protocol):
    """Sandbox protocol for executing commands in isolated environment."""

    async def start(self) -> None:
        """Start the sandbox environment."""
        ...

    async def stop(self) -> None:
        """Stop and cleanup the sandbox environment."""
        ...

    async def exec_command(self, command: str, timeout: int = 30) -> ExecResult:
        """Execute a command in the sandbox."""
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Write content to a file in the sandbox."""
        ...

    async def read_file(self, path: str) -> str:
        """Read content from a file in the sandbox."""
        ...

    async def __aenter__(self) -> "BaseSandbox":
        """Async context manager entry."""
        ...

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        ...
