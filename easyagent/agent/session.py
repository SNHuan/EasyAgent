from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, AsyncIterator

from easyagent.context.base import BaseContext
from easyagent.memory.base import BaseMemory
from easyagent.model.schema import Message
from easyagent.agent.serialization import serialize_session_messages

if TYPE_CHECKING:
    from easyagent.agent.base import BaseAgent
    from easyagent.checkpoint import AgentCheckpoint, CheckpointStore
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


class SessionNotResumableError(RuntimeError):
    """Raised when ``resume()`` is invalid for the current Session."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Session cannot resume: {reason}")


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
    checkpoint_store: CheckpointStore | None = None
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
    _stop_requested: bool = field(default=False, init=False, repr=False)
    _stop_payload: Any = field(default=None, init=False, repr=False)
    _restored_from_checkpoint: bool = field(
        default=False,
        init=False,
        repr=False,
    )
    _resume_consumed: bool = field(
        default=False,
        init=False,
        repr=False,
    )

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
        assert self.agent is not None, "Session.step requires session.agent to be set"
        return await self.agent.step(self)

    def create_checkpoint(self) -> AgentCheckpoint:
        """Capture current state; manual callers choose a safe boundary."""
        from easyagent.checkpoint import AgentCheckpoint

        return AgentCheckpoint.capture(self)

    async def save_checkpoint(self) -> AgentCheckpoint | None:
        """Persist current state; managed loops call this at safe boundaries."""
        if self.checkpoint_store is None:
            return None
        checkpoint = self.create_checkpoint()
        await self.checkpoint_store.save(checkpoint)
        return checkpoint

    async def _record_step(self, result: LoopStepResult) -> None:
        self.loop_steps.append(result)
        await self.save_checkpoint()

    def request_stop(self, *, reason: str = "", data: Any = None) -> None:
        """Request a graceful stop at the next agent loop boundary.

        This is a control-plane operation. Callers may publish a ``StopEvent``
        separately when they also want an observable notification.
        """
        self.metadata["stop_reason"] = reason
        self._stop_payload = data if data is not None else reason
        self._stop_requested = True

    def _consume_stop_request(self) -> LoopStepResult | None:
        if not self._stop_requested:
            return None
        payload = self._stop_payload
        self._stop_requested = False
        self._stop_payload = None
        final_text = payload if isinstance(payload, str) else str(payload)
        self.final_output = final_text
        return LoopStepResult(
            status=StepStatus.EARLY_EXIT,
            output=final_text,
        )

    async def run(
        self,
        user_input: Any,
        *,
        event_bus: "EventBus | None" = None,
    ) -> str:
        """Run one task through the complete Agent lifecycle."""
        assert self.agent is not None, "Session.run requires session.agent to be set"
        if event_bus is not None:
            self.event_bus = event_bus
        return await self._run_lifecycle(
            lambda: self.agent.run_session(self, user_input)
        )

    async def run_prepared(
        self,
        *,
        event_bus: "EventBus | None" = None,
    ) -> str:
        """Run the lifecycle for messages already prepared in session memory."""
        assert self.agent is not None, "Session.run_prepared requires session.agent to be set"
        if event_bus is not None:
            self.event_bus = event_bus
        return await self._run_lifecycle(
            lambda: self.agent.run_prepared_session(self)
        )

    async def resume(
        self,
        *,
        event_bus: "EventBus | None" = None,
    ) -> str:
        """Continue a restored checkpoint through the Agent lifecycle."""
        assert self.agent is not None, "Session.resume requires session.agent to be set"
        if not self._restored_from_checkpoint:
            raise SessionNotResumableError("not_restored")
        if self._resume_consumed:
            raise SessionNotResumableError("already_resumed")
        if self.status is not AgentStatus.RUNNING:
            raise SessionNotResumableError("checkpoint_not_running")
        self._resume_consumed = True
        if event_bus is not None:
            self.event_bus = event_bus
        return await self._run_lifecycle(
            lambda: self.agent.resume_session(self)
        )

    def _mark_restored_from_checkpoint(self) -> None:
        self._restored_from_checkpoint = True
        self._resume_consumed = False

    async def _run_lifecycle(
        self,
        operation: Callable[[], Awaitable[str]],
    ) -> str:
        assert self.agent is not None
        error: BaseException | None = None
        result = ""

        try:
            await self._start()
            result = await operation()
        except BaseException as exc:
            error = exc
            await self._report_failure(exc)

        error = await self._end_lifecycle(error)
        if error is not None:
            raise error

        try:
            await self._complete(result)
        except BaseException as exc:
            await self._report_failure(exc)
            raise
        return result

    async def stream(
        self,
        user_input: Any,
        *,
        event_bus: "EventBus | None" = None,
    ) -> AsyncIterator[str]:
        """Stream one task through the complete Agent lifecycle."""
        assert self.agent is not None, "Session.stream requires session.agent to be set"
        if event_bus is not None:
            self.event_bus = event_bus

        error: BaseException | None = None
        try:
            await self._start()
            async for chunk in self.agent.stream_session(self, user_input):
                yield chunk
        except BaseException as exc:
            error = exc
            await self._report_failure(exc)

        error = await self._end_lifecycle(error)
        if error is not None:
            raise error

        try:
            await self._complete(self.final_output or "")
        except BaseException as exc:
            await self._report_failure(exc)
            raise

    async def invoke(self, user_input: Any) -> str:
        """Compatibility alias for code that still calls ``session.invoke``."""
        return await self.run(user_input)

    async def _start(self) -> None:
        assert self.agent is not None
        self.status = AgentStatus.RUNNING
        if self.event_bus is not None:
            from easyagent.events import AgentStartedEvent

            await self.event_bus.publish(
                AgentStartedEvent(
                    agent_id=self.session_id,
                    metadata=dict(self.metadata),
                )
            )
        await self.agent.on_session_start(self)

    async def _complete(self, output: str) -> None:
        self.final_output = output
        self.status = AgentStatus.COMPLETED
        await self.save_checkpoint()
        if self.event_bus is not None:
            from easyagent.events import AgentFinishedEvent

            await self.event_bus.publish(
                AgentFinishedEvent(
                    agent_id=self.session_id,
                    output=output,
                    messages=serialize_session_messages(self.get_all_messages()),
                )
            )

    async def _fail(self, exc: BaseException) -> None:
        self.status = AgentStatus.FAILED
        if self.event_bus is not None:
            from easyagent.events import AgentFailedEvent

            await self.event_bus.publish(
                AgentFailedEvent(
                    agent_id=self.session_id,
                    error=str(exc) or type(exc).__name__,
                    messages=serialize_session_messages(self.get_all_messages()),
                )
            )

    async def _report_failure(self, exc: BaseException) -> None:
        try:
            await self._fail(exc)
        except BaseException as reporting_error:
            exc.add_note(
                "Failed to publish the session failure event: "
                f"{type(reporting_error).__name__}: {reporting_error}"
            )

    async def _end_lifecycle(
        self,
        error: BaseException | None,
    ) -> BaseException | None:
        assert self.agent is not None
        try:
            await self.agent.on_session_end(self)
        except BaseException as cleanup_error:
            if error is None:
                await self._report_failure(cleanup_error)
                return cleanup_error
            error.add_note(
                "Session cleanup also failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
        return error

    async def on_events(self, events: list[BaseEvent]) -> list[BaseEvent]:
        """Compatibility adapter for event-driven session callers.

        Runtime entities now translate events into ``session.run(...)`` calls
        directly. This method remains available for callers that still hand an
        event batch to a session.

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
