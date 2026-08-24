from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Self

from easyagent.hooks.base import BaseHook
from easyagent.tool.base import ToolResult

if TYPE_CHECKING:
    from easyagent.agent.session import AgentSession


@dataclass(frozen=True)
class BeforeToolCallResult:
    """Optional argument replacement or execution block from a hook."""

    arguments: dict[str, Any] | None = None
    block: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class BeforeToolCallHook(BaseHook):
    session: AgentSession
    tool_name: str
    arguments: dict[str, Any]
    blocked: bool = False
    reason: str | None = None

    def apply(self, result: Any) -> Self:
        if result is None:
            return self
        if not isinstance(result, BeforeToolCallResult):
            raise TypeError(
                "BeforeToolCallHook handlers must return "
                "BeforeToolCallResult or None"
            )
        return replace(
            self,
            arguments=(
                dict(result.arguments)
                if result.arguments is not None
                else self.arguments
            ),
            blocked=self.blocked or result.block,
            reason=result.reason if result.reason is not None else self.reason,
        )

    @property
    def stopped(self) -> bool:
        return self.blocked


@dataclass(frozen=True)
class AfterToolCallHook(BaseHook):
    session: AgentSession
    tool_name: str
    arguments: dict[str, Any]
    result: ToolResult

    def apply(self, result: Any) -> Self:
        if result is None:
            return self
        if not isinstance(result, ToolResult):
            raise TypeError(
                "AfterToolCallHook handlers must return ToolResult or None"
            )
        return replace(self, result=result)
