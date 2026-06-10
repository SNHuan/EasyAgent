from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Literal

from easyagent.external.base import ExternalEventHandler, ExternalResult
from easyagent.external.entity import ExternalAgentEntity, InputMapper, OutputMapper

CodexSandboxName = Literal["read_only", "workspace_write", "full_access"]
CodexApprovalModeName = Literal["deny_all", "auto_review"]


class CodexRunner:
    """Thin adapter from OpenAI Codex SDK to EasyAgent's ExternalRunner protocol."""

    def __init__(
        self,
        *,
        cwd: str | Path | None = None,
        model: str | None = None,
        sandbox: CodexSandboxName | None = "read_only",
        approval_mode: CodexApprovalModeName = "deny_all",
        developer_instructions: str | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve() if cwd is not None else Path.cwd()
        self.model = model
        self.sandbox = sandbox
        self.approval_mode = approval_mode
        self.developer_instructions = developer_instructions

    async def run(
        self,
        prompt: str,
        *,
        metadata: dict[str, Any] | None = None,
        event_handler: ExternalEventHandler | None = None,
    ) -> ExternalResult:
        try:
            from openai_codex import ApprovalMode, AsyncCodex, Sandbox
            from openai_codex._run import TurnResult, _final_assistant_response_from_items, _raise_for_failed_turn
            from openai_codex.generated.v2_all import (
                ItemCompletedNotification,
                ThreadTokenUsageUpdatedNotification,
                TurnCompletedNotification,
            )
        except ImportError as exc:
            raise ImportError(
                'Codex support requires `pip install -e ".[external]"` '
                "or `pip install openai-codex`."
            ) from exc

        sandbox = _resolve_sandbox(Sandbox, self.sandbox)
        approval_mode = _resolve_approval_mode(ApprovalMode, self.approval_mode)

        async with AsyncCodex() as codex:
            thread = await codex.thread_start(
                cwd=str(self.cwd),
                model=self.model,
                sandbox=sandbox,
                approval_mode=approval_mode,
                developer_instructions=self.developer_instructions,
            )
            turn = await thread.turn(
                prompt,
                cwd=str(self.cwd),
                model=self.model,
                sandbox=sandbox,
                approval_mode=approval_mode,
            )
            items: list[Any] = []
            usage: Any | None = None
            completed: Any | None = None
            events: list[dict[str, Any]] = []
            async for notification in turn.stream():
                notification_events = _notification_to_events(notification)
                if event_handler is None:
                    events.extend(notification_events)
                else:
                    for event in notification_events:
                        await event_handler(event)
                payload = notification.payload
                if isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn.id:
                    items.append(payload.item)
                elif isinstance(payload, ThreadTokenUsageUpdatedNotification) and payload.turn_id == turn.id:
                    usage = payload.token_usage
                elif isinstance(payload, TurnCompletedNotification) and payload.turn.id == turn.id:
                    completed = payload

            if completed is None:
                raise RuntimeError("Codex turn completed event not received")
            _raise_for_failed_turn(completed.turn)
            result = TurnResult(
                id=completed.turn.id,
                status=completed.turn.status,
                error=completed.turn.error,
                started_at=completed.turn.started_at,
                completed_at=completed.turn.completed_at,
                duration_ms=completed.turn.duration_ms,
                final_response=_final_assistant_response_from_items(items),
                items=items,
                usage=usage,
            )

        return ExternalResult(
            content=result.final_response or "",
            provider="codex",
            session_id=getattr(thread, "id", None),
            usage=_usage_to_dict(result.usage),
            events=[*events, *_result_to_events(result)],
            metadata={
                "cwd": str(self.cwd),
                "model": self.model,
                "sandbox": self.sandbox,
                "approval_mode": self.approval_mode,
                **(metadata or {}),
            },
        )


def codex_entity(
    id: str,
    *,
    cwd: str | Path | None = None,
    model: str | None = None,
    sandbox: CodexSandboxName | None = "read_only",
    approval_mode: CodexApprovalModeName = "deny_all",
    developer_instructions: str | None = None,
    name: str | None = None,
    input_mapper: InputMapper | None = None,
    output_mapper: OutputMapper | None = None,
    trace_level: str = "summary",
) -> ExternalAgentEntity:
    return ExternalAgentEntity(
        id,
        runner=CodexRunner(
            cwd=cwd,
            model=model,
            sandbox=sandbox,
            approval_mode=approval_mode,
            developer_instructions=developer_instructions,
        ),
        provider="codex",
        name=name,
        input_mapper=input_mapper,
        output_mapper=output_mapper,
        trace_level=trace_level,
    )


def _resolve_sandbox(sandbox_cls: Any, sandbox: CodexSandboxName | None) -> Any:
    if sandbox is None:
        return None
    try:
        return getattr(sandbox_cls, sandbox)
    except AttributeError as exc:
        raise ValueError("sandbox must be one of: read_only, workspace_write, full_access") from exc


def _resolve_approval_mode(approval_mode_cls: Any, approval_mode: CodexApprovalModeName | None) -> Any:
    if approval_mode is None:
        return None
    try:
        return getattr(approval_mode_cls, approval_mode)
    except AttributeError as exc:
        raise ValueError("approval_mode must be one of: deny_all, auto_review") from exc


def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if is_dataclass(usage):
        return asdict(usage)
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return dict(usage)
    return {"value": str(usage)}


def _result_to_events(result: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if result.final_response:
        events.append({"type": "message", "role": "assistant", "content": result.final_response})
    payload: dict[str, Any]
    if is_dataclass(result):
        payload = asdict(result)
    elif hasattr(result, "model_dump"):
        payload = result.model_dump()
    else:
        payload = {"value": str(result)}
    events.append(
        {
            "type": "result",
            "summary": str(getattr(result, "status", "codex result")),
            "duration_ms": getattr(result, "duration_ms", None),
            "raw": payload,
        }
    )
    return events


def _notification_to_events(notification: Any) -> list[dict[str, Any]]:
    method = str(getattr(notification, "method", "notification"))
    payload = getattr(notification, "payload", None)
    payload_dict = _payload_to_dict(payload)
    if method == "item/agentMessage/delta":
        return [
            {
                "type": "message_delta",
                "role": "assistant",
                "content": str(getattr(payload, "delta", "")),
                "method": method,
                "item_id": getattr(payload, "item_id", None),
                "raw": payload_dict,
            }
        ]
    if method in {
        "item/commandExecution/outputDelta",
        "item/fileChange/outputDelta",
        "command/exec/outputDelta",
        "process/outputDelta",
    }:
        return [
            {
                "type": "tool_result",
                "name": "command",
                "content": str(getattr(payload, "delta", "")),
                "method": method,
            }
        ]
    if method in {"item/started", "item/completed"}:
        return [{"type": "provider", "summary": method, "method": method, "raw": payload_dict}]
    if method in {"turn/planUpdated", "item/plan/delta"}:
        return [{"type": "provider", "summary": "plan updated", "method": method, "raw": payload_dict}]
    if method == "turn/diffUpdated":
        return [{"type": "provider", "summary": "diff updated", "method": method, "raw": payload_dict}]
    if method == "turn/completed":
        return [{"type": "result", "summary": "turn completed", "method": method, "raw": payload_dict}]
    return [{"type": "provider", "summary": method, "method": method, "raw": payload_dict}]


def _payload_to_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if is_dataclass(payload):
        return asdict(payload)
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return dict(payload)
    return {"value": str(payload)}
