"""Local sandbox implementation (for development/testing)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from easyagent.sandbox.base import ExecResult


class LocalSandbox:
    """Sandbox using local shell (no isolation, for development only)."""

    def __init__(self, workdir: str | None = None) -> None:
        self._workdir = str(Path(workdir).resolve()) if workdir else None
        self._owns_default_workdir = workdir is None

    @property
    def workdir(self) -> str:
        if self._workdir:
            return self._workdir
        raise RuntimeError("Sandbox not started")

    async def start(self) -> None:
        """Create the default workspace directory if no workdir was provided."""
        if not self._workdir:
            self._workdir = str((Path.cwd() / "agent_workspace").resolve())
        Path(self._workdir).mkdir(parents=True, exist_ok=True)

    async def stop(self) -> None:
        """Local sandbox keeps its workspace directory for inspection."""
        return None

    async def exec_command(self, command: str, timeout: int = 30) -> ExecResult:
        """Execute command locally."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.workdir,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode(),
                stderr=stderr.decode(),
            )
        except asyncio.TimeoutError:
            proc.kill()
            return ExecResult(exit_code=-1, stdout="", stderr=f"Command timed out after {timeout}s")

    async def write_file(self, path: str, content: str) -> None:
        """Write file to workdir."""
        file_path = Path(self.workdir) / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    async def read_file(self, path: str) -> str:
        """Read file from workdir."""
        file_path = Path(self.workdir) / path
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return file_path.read_text()

    async def __aenter__(self) -> "LocalSandbox":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()
