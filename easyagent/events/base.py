from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BaseEvent:
    """Root of the event hierarchy.

    Everything that flows through the EventBus is a BaseEvent. Concrete event
    types declare their payload as typed fields on the subclass — there is no
    untyped ``data`` dict. ``MessageEvent`` is the only built-in primitive for
    agent-to-agent communication; all other events (lifecycle, tool, LLM,
    user-defined) are sibling subclasses.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
