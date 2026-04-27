from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from easyagent.context.base import BaseContext
from easyagent.memory.base import BaseMemory
from easyagent.model.schema import Message

if TYPE_CHECKING:
    from easyagent.agent.base import BaseAgent
    from easyagent.events.base import BaseEvent
    from easyagent.events.bus import EventBus
    from easyagent.sandbox.base import BaseSandbox


class StepStatus(str, Enum):
    CONTINUE = "continue"
    COMPLETED = "completed"
    EARLY_EXIT = "early_exit"
    MAX_ITERATIONS = "max_iterations"
    FAILED = "failed"


@dataclass(slots=True)
class LoopStepResult:
    status: StepStatus
    output: str | None = None

    @property
    def done(self) -> bool:
        return self.status is not StepStatus.CONTINUE


@dataclass(slots=True)
class AgentRunResult:
    """Completed result for one ``agent.run(...)`` call."""

    session: "AgentSession"
    final_output: str | None
    messages: list[Message]
    loop_steps: list[LoopStepResult]
    status: "AgentStatus"
    iteration_count: int
    enabled_tools: list[str]
    loaded_skills: list[str]
    metadata: dict[str, Any]

    @classmethod
    def from_session(cls, session: "AgentSession") -> "AgentRunResult":
        return cls(
            session=session,
            final_output=session.final_output,
            messages=session.get_all_messages(),
            loop_steps=list(session.loop_steps),
            status=session.status,
            iteration_count=session.iteration_count,
            enabled_tools=list(session.enabled_tools),
            loaded_skills=list(session.loaded_skills),
            metadata=dict(session.metadata),
        )

    def __str__(self) -> str:
        return self.final_output or ""


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentSession:
    """A running instance ("分身") of an Agent.

    AgentSession holds the per-instance runtime state:
      - independent memory and context renderer
      - which tools / skills are currently enabled
      - capability-owned resources (e.g. the active sandbox)
      - loop bookkeeping for the in-flight task

    The Agent it belongs to is reached through ``self.agent``. Loops read
    ``session.agent.default_model`` rather than holding their own model
    reference; Runtime injects ``event_bus`` when this session lives inside
    a multi-agent environment.
    """

    session_id: str = ""
    agent: BaseAgent | None = None
    memory: BaseMemory | None = None
    context: BaseContext | None = None
    enabled_tools: list[str] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)
    sandbox: BaseSandbox | None = None
    resources: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    event_bus: EventBus | None = None
    status: AgentStatus = AgentStatus.IDLE
    iteration_count: int = 0
    final_output: str | None = None
    loop_steps: list[LoopStepResult] = field(default_factory=list)
    loop_state: dict[str, Any] = field(default_factory=dict)

    def add_message(self, message: Message) -> None:
        assert self.memory is not None, "Session has no memory; only Agent-created sessions support add_message"
        self.memory.add(message)

    def get_all_messages(self) -> list[Message]:
        assert self.memory is not None, "Session has no memory; only Agent-created sessions support get_all_messages"
        return self.memory.get_all()

    async def get_model_messages(self, system_prompt: str) -> list[dict[str, Any]]:
        assert self.memory is not None and self.context is not None, (
            "Session has no memory/context; only Agent-created sessions support get_model_messages"
        )
        return await self.context.build_messages(self.memory, system_prompt)

    async def step(self) -> LoopStepResult:
        """Run one execution step for this session.

        ``Agent`` defines the behavior, while ``AgentSession`` owns all
        execution state. Messages should already be in memory before calling
        step — use ``add_message(Message.user(...))`` to add input first.
        """
        assert self.agent is not None, "Session.invoke requires session.agent to be set"
        return await self.agent.step(self)

    async def run(self, user_input: Any) -> str:
        """Drive ``step`` until the session reaches a terminal result."""
        assert self.agent is not None, "Session.run requires session.agent to be set"
        return await self.agent.run_session(self, user_input)

    async def invoke(self, user_input: Any) -> str:
        """Compatibility alias for code that still calls ``session.invoke``."""
        return await self.run(user_input)

    async def on_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        """Process a batch of events and produce response events.

        This is the unified entry point used by both ``Agent.run`` (single-task
        invocation) and Runtime (multi-agent orchestration). Subclasses override
        this to customize how events become memory updates, how the loop is
        driven, and how the loop's output is packaged back into events.

        Default behavior (conservative — opt into broadcast in your subclass):
          - Each non-self ``MessageEvent`` is appended to memory as a user
            message (tagged with the sender, except when sender=="user").
          - The last incoming non-self ``MessageEvent`` is fed to
            ``self.invoke(...)`` as the active task.
          - The loop's final output is replied **only to that last sender**.
            If the original event was a broadcast (``to == "*"``), the reply
            is also a broadcast — preserving "this was a public conversation".
            Otherwise the reply is a direct message back to the sender.
          - All other event types are ignored by default.

        Group-chat-style sessions should override ``step`` to broadcast (or
        route via ``@xxx`` parsing) explicitly — see ``examples/group_chat_demo.py``.
        """
        from easyagent.events.types import MessageEvent

        incoming: list[MessageEvent] = []
        for event in events:
            if not isinstance(event, MessageEvent):
                continue
            if event.sender == self.session_id:
                continue
            incoming.append(event)

        if not incoming:
            return []

        # All but the last incoming message become memory entries (with a
        # sender tag for multi-agent context). The last one is handed to the
        # loop as the "active task" — the loop itself appends it to memory,
        # so we don't double-write.
        last = incoming[-1]
        for event in incoming[:-1]:
            if event.sender == "user":
                self.add_message(Message.user(event.content))
            else:
                self.add_message(Message.user(f"[{event.sender}] {event.content}"))

        if last.sender == "user":
            loop_input: str = last.content
        else:
            loop_input = f"[{last.sender}] {last.content}"

        result = await self.run(loop_input)
        if not result.strip() or result == "Max iterations reached":
            return []

        # Conservative reply routing: preserve the conversation's visibility.
        # If the prompting message was a broadcast, broadcast back. Otherwise
        # reply directly to its sender — this prevents accidental group-chat
        # self-amplification when a SDK user spawns multiple agents without
        # overriding step.
        reply_to = "*" if last.is_broadcast else frozenset({last.sender})
        return [MessageEvent(sender=self.session_id, to=reply_to, content=result)]
