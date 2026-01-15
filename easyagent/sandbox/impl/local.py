"""Local sandbox implementation (for development/testing)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from easyagent.sandbox.base import ExecResult


class LocalSandbox:
    """Sandbox using local shell (no isolation, for development only)."""

    def __init__(self, workdir: str | None = None) -> None:
        self._workdir = workdir
        self._temp_dir: tempfile.TemporaryDirectory | None = None

    @property
    def workdir(self) -> str:
        if self._workdir:
            return self._workdir
        if self._temp_dir:
            return self._temp_dir.name
        raise RuntimeError("Sandbox not started")

    async def start(self) -> None:
        """Create temp directory if no workdir specified."""
        if not self._workdir:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="easyagent_sandbox_")

    async def stop(self) -> None:
        """Cleanup temp directory."""
        if self._temp_dir:
            self._temp_dir.cleanup()
            self._temp_dir = None

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
        file_path.write_text(content)

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
