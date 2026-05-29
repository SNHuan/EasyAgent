from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


DisplaySurface = Literal["messages", "timeline", "summary", "metric", "payload", "hidden"]
DisplayRole = Literal["system", "user", "assistant", "tool"]


@dataclass
class DisplayHint:
    """Dashboard display metadata for custom trace events.

    ``DisplayHint`` is intentionally stored inside the event payload so trace
    stores do not need a schema migration. Dashboards may use it to project a
    custom event into a specific UI surface while still keeping the full event
    payload inspectable.
    """

    surface: DisplaySurface = "payload"
    role: DisplayRole | None = None
    title: str | None = None
    content: str | None = None
    source: str | None = None
    icon: str | None = None
    color: str | None = None
    priority: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def messages(
        cls,
        content: str,
        *,
        role: DisplayRole = "assistant",
        title: str | None = None,
        source: str | None = None,
        **metadata: Any,
    ) -> "DisplayHint":
        return cls(
            surface="messages",
            role=role,
            title=title,
            content=content,
            source=source,
            metadata=metadata,
        )

    @classmethod
    def timeline(
        cls,
        summary: str,
        *,
        title: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        **metadata: Any,
    ) -> "DisplayHint":
        return cls(
            surface="timeline",
            title=title,
            content=summary,
            icon=icon,
            color=color,
            metadata=metadata,
        )

    @classmethod
    def payload(cls) -> "DisplayHint":
        return cls(surface="payload")

    @classmethod
    def hidden(cls) -> "DisplayHint":
        return cls(surface="hidden")
