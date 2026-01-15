"""Bash command execution tool."""

from typing import Any

from easyagent.tool.manager import register_tool
from easyagent.sandbox import get_sandbox


@register_tool
class Bash:
    """Execute bash commands in sandbox environment."""

    name = "bash"
    type = "function"
    description = (
        "Execute a bash command in the sandbox environment. "
        "Returns stdout/stderr and exit code. "
        "For writing files with complex content, use write_file tool instead."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Command timeout in seconds (default: 30)",
            },
        },
        "required": ["command"],
    }

    def init(self) -> None:
        pass

    async def execute(self, command: str, timeout: int = 30, **kwargs: Any) -> str:
        """Execute bash command."""
        sandbox = get_sandbox()
        if sandbox is None:
            return "Error: No sandbox configured. Please set up a sandbox first."

        result = await sandbox.exec_command(command, timeout=timeout)
        return result.output
