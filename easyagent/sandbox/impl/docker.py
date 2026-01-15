"""Docker sandbox implementation."""

from __future__ import annotations

import asyncio
from typing import Any

from easyagent.sandbox.base import ExecResult


class DockerSandbox:
    """Sandbox using Docker container."""

    def __init__(
        self,
        image: str = "python:3.12-slim",
        name: str | None = None,
        workdir: str = "/workspace",
        memory_limit: str = "512m",
        cpu_limit: float = 1.0,
        network: bool = True,
    ) -> None:
        self.image = image
        self.name = name
        self.workdir = workdir
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network = network
        self._container_id: str | None = None

    async def start(self) -> None:
        """Start Docker container."""
        cmd = [
            "docker", "run", "-d",
            "--workdir", self.workdir,
            "--memory", self.memory_limit,
            "--cpus", str(self.cpu_limit),
        ]
        if self.name:
            cmd.extend(["--name", self.name])
        if not self.network:
            cmd.extend(["--network", "none"])
        cmd.extend([self.image, "tail", "-f", "/dev/null"])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start container: {stderr.decode()}")
        self._container_id = stdout.decode().strip()

    async def stop(self) -> None:
        """Stop and remove Docker container."""
        if not self._container_id:
            return
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", self._container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        self._container_id = None

    async def exec_command(self, command: str, timeout: int = 30) -> ExecResult:
        """Execute command in container."""
        if not self._container_id:
            raise RuntimeError("Container not started")

        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", self._container_id, "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
        """Write file to container."""
        if not self._container_id:
            raise RuntimeError("Container not started")
        # Use docker exec with stdin
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", self._container_id,
            "bash", "-c", f"cat > {path}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=content.encode())

    async def read_file(self, path: str) -> str:
        """Read file from container."""
        result = await self.exec_command(f"cat {path}")
        if not result.success:
            raise FileNotFoundError(f"File not found: {path}")
        return result.stdout

    async def __aenter__(self) -> "DockerSandbox":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()
