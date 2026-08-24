from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from easyagent.agent.session import AgentSession
    from easyagent.events.bus import EventBus
    from easyagent.sandbox.base import BaseSandbox


@dataclass(frozen=True)
class ToolContext:
    """Runtime dependencies available to every context-aware tool."""

    session: AgentSession

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @property
    def sandbox(self) -> BaseSandbox | None:
        return self.session.sandbox

    @property
    def event_bus(self) -> EventBus | None:
        return self.session.event_bus

    @property
    def metadata(self) -> dict[str, Any]:
        return self.session.metadata


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Context-aware tool Interface.

    Existing ``execute(**kwargs)`` tools remain supported through the
    ToolManager's legacy Adapter. Concrete context-aware tools declare
    ``context_aware = True`` so legacy Tool subclasses remain unambiguous.
    """

    context_aware: bool = False
    name: str
    type: str = "function"
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult: ...

