"""File operation tools for sandbox."""

from typing import Any

from easyagent.tool.manager import register_tool
from easyagent.sandbox import get_sandbox


@register_tool
class WriteFile:
    """Write content to a file in sandbox."""

    name = "write_file"
    type = "function"
    description = (
        "Write content to a file in the sandbox. "
        "Use this for creating/modifying files with code or complex content. "
        "Handles special characters and multi-line content safely."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to sandbox workdir",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
        },
        "required": ["path", "content"],
    }

    def init(self) -> None:
        pass

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        """Write content to file."""
        sandbox = get_sandbox()
        if sandbox is None:
            return "Error: No sandbox configured. Please set up a sandbox first."

        try:
            await sandbox.write_file(path, content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"


@register_tool
class ReadFile:
    """Read content from a file in sandbox."""

    name = "read_file"
    type = "function"
    description = "Read content from a file in the sandbox. Returns the file content as text."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to sandbox workdir",
            },
        },
        "required": ["path"],
    }

    def init(self) -> None:
        pass

    async def execute(self, path: str, **kwargs: Any) -> str:
        """Read content from file."""
        sandbox = get_sandbox()
        if sandbox is None:
            return "Error: No sandbox configured. Please set up a sandbox first."

        try:
            return await sandbox.read_file(path)
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except Exception as e:
            return f"Error reading file: {e}"
