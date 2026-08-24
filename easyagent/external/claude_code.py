from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from easyagent.external.base import ExternalEventHandler, ExternalResult, ExternalRunRequest
from easyagent.external.entity import ExternalAgentEntity, InputMapper, OutputMapper


class ClaudeCodeRunner:
    """Thin adapter from Claude Code SDK to EasyAgent's ExternalRunner protocol."""

    def __init__(
        self,
        *,
        cwd: str | Path | None = None,
        max_turns: int = 3,
        allowed_tools: list[str] | None = None,
        permission_mode: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve() if cwd is not None else Path.cwd()
        self.max_turns = max_turns
        self.allowed_tools = allowed_tools or ["Read", "Glob", "Grep"]
        self.permission_mode = permission_mode
        self.system_prompt = system_prompt
        self.model = model

    async def run(
        self,
        request: ExternalRunRequest | str,
        *,
        metadata: dict[str, Any] | None = None,
        event_handler: ExternalEventHandler | None = None,
    ) -> ExternalResult:
        if isinstance(request, str):
            request = ExternalRunRequest(
                prompt=request,
                metadata=dict(metadata or {}),
            )
        elif metadata is not None:
            raise TypeError("metadata is only supported with a string prompt")
        return await self.run_request(request, event_handler=event_handler)

    async def run_request(
        self,
        request: ExternalRunRequest,
        *,
        event_handler: ExternalEventHandler | None = None,
    ) -> ExternalResult:
        try:
            from claude_code_sdk import AssistantMessage, ClaudeCodeOptions, ResultMessage, TextBlock, query
        except ImportError as exc:
            raise ImportError(
                'Claude Code support requires `pip install -e ".[external]"` '
                "or `pip install claude-code-sdk`."
            ) from exc

        result_message: Any | None = None
        assistant_parts: list[str] = []
        events: list[dict[str, Any]] = []

        options = ClaudeCodeOptions(
            cwd=self.cwd,
            max_turns=self.max_turns,
            allowed_tools=self.allowed_tools,
            permission_mode=self.permission_mode,
            system_prompt=self.system_prompt,
            model=self.model,
            resume=request.session_id,
        )

        async for message in query(prompt=request.prompt, options=options):
            message_events = _message_to_events(message)
            if event_handler is None:
                events.extend(message_events)
            else:
                for event in message_events:
                    await event_handler(event)
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        assistant_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                result_message = message

        content = (
            result_message.result
            if result_message is not None and result_message.result
            else "\n".join(part for part in assistant_parts if part).strip()
        )
        usage = result_message.usage if result_message is not None and result_message.usage else {}
        if result_message is not None and result_message.total_cost_usd is not None:
            usage = {**usage, "cost": result_message.total_cost_usd}

        return ExternalResult(
            content=content or "",
            provider="claude_code",
            session_id=result_message.session_id if result_message is not None else None,
            usage=usage,
            events=events,
            metadata={
                "cwd": str(self.cwd),
                "allowed_tools": self.allowed_tools,
                "max_turns": self.max_turns,
                "model": self.model,
                **request.metadata,
            },
        )


def claude_code_entity(
    id: str,
    *,
    cwd: str | Path | None = None,
    max_turns: int = 3,
    allowed_tools: list[str] | None = None,
    permission_mode: str | None = None,
    system_prompt: str | None = None,
    model: str | None = None,
    name: str | None = None,
    input_mapper: InputMapper | None = None,
    output_mapper: OutputMapper | None = None,
    trace_level: str = "summary",
) -> ExternalAgentEntity:
    return ExternalAgentEntity(
        id,
        runner=ClaudeCodeRunner(
            cwd=cwd,
            max_turns=max_turns,
            allowed_tools=allowed_tools,
            permission_mode=permission_mode,
            system_prompt=system_prompt,
            model=model,
        ),
        provider="claude_code",
        name=name,
        input_mapper=input_mapper,
        output_mapper=output_mapper,
        trace_level=trace_level,
    )


def _message_to_events(message: Any) -> list[dict[str, Any]]:
    try:
        from claude_code_sdk import AssistantMessage, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage
    except ImportError:
        return [{"type": "provider", "summary": message.__class__.__name__, "raw": str(message)}]

    if isinstance(message, AssistantMessage):
        events: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                events.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": block.text,
                        "model": message.model,
                    }
                )
            elif isinstance(block, ToolUseBlock):
                events.append(
                    {
                        "type": "tool_call",
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input,
                        "model": message.model,
                    }
                )
            elif isinstance(block, ToolResultBlock):
                events.append(
                    {
                        "type": "tool_result",
                        "id": block.tool_use_id,
                        "name": block.tool_use_id,
                        "content": block.content,
                        "is_error": block.is_error,
                        "model": message.model,
                    }
                )
            elif is_dataclass(block):
                events.append({"type": "provider", "summary": block.__class__.__name__, "raw": asdict(block)})
            else:
                events.append({"type": "provider", "summary": block.__class__.__name__, "raw": str(block)})
        return events

    if isinstance(message, UserMessage):
        if not isinstance(message.content, list):
            return [{"type": "provider", "summary": message.__class__.__name__, "raw": _safe_raw(message)}]
        events = []
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                events.append(
                    {
                        "type": "tool_result",
                        "id": block.tool_use_id,
                        "name": block.tool_use_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    }
                )
            elif is_dataclass(block):
                events.append({"type": "provider", "summary": block.__class__.__name__, "raw": asdict(block)})
            else:
                events.append({"type": "provider", "summary": block.__class__.__name__, "raw": str(block)})
        return events

    if isinstance(message, ResultMessage):
        return [
            {
                "type": "result",
                "summary": message.subtype,
                "session_id": message.session_id,
                "is_error": message.is_error,
                "num_turns": message.num_turns,
                "duration_ms": message.duration_ms,
                "duration_api_ms": message.duration_api_ms,
                "total_cost_usd": message.total_cost_usd,
                "usage": message.usage,
                "content": message.result,
            }
        ]

    if is_dataclass(message):
        return [{"type": "provider", "summary": message.__class__.__name__, "raw": asdict(message)}]
    return [{"type": "provider", "summary": message.__class__.__name__, "raw": str(message)}]


def _safe_raw(message: Any) -> Any:
    return asdict(message) if is_dataclass(message) else str(message)
