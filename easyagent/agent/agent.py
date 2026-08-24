from __future__ import annotations

from copy import deepcopy
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator

from easyagent.agent.base import BaseAgent
from easyagent.agent.serialization import serialize_messages, serialize_tool_calls
from easyagent.agent.session import AgentRunResult, AgentSession, AgentStatus, LoopStepResult, StepStatus
from easyagent.checkpoint.compatibility import (
    CheckpointCompatibilityIssue,
    CheckpointCompatibilityReport,
    IncompatibleCheckpointError,
)
from easyagent.checkpoint.schema import (
    AgentCheckpoint,
    InvalidCheckpointStateError,
)
from easyagent.context.base import BaseContext
from easyagent.context.sliding import SlidingWindowContext
from easyagent.debug.log import Logger
from easyagent.hooks import HookManager
from easyagent.memory.base import BaseMemory
from easyagent.memory.inmemory import InMemoryMemory
from easyagent.model.base import BaseLLM
from easyagent.model.schema import Message

if TYPE_CHECKING:
    from easyagent.checkpoint import CheckpointStore
    from easyagent.events import EventBus


class Agent(BaseAgent):
    """Base agent — single-turn LLM call.

    Subclasses add richer behavior:
      - ``ReactAgent``  — tool calling + ReAct loop
      - ``SkillAgent``  — on-demand skill loading
      - ``SandboxAgent`` — sandboxed code execution
    """

    def __init__(
        self,
        model: BaseLLM,
        *,
        name: str = "",
        description: str = "",
        memory: BaseMemory | None = None,
        context: BaseContext | None = None,
        system_prompt: str = "",
        max_steps: int = 1,
        session_class: type[AgentSession] | None = None,
        hooks: HookManager | None = None,
        checkpoint_store: CheckpointStore | None = None,
        checkpoint_identity: str | None = None,
    ):
        self._default_model = model
        self._system_prompt = system_prompt
        self.name = name
        self.description = description
        self._memory_factory = memory or InMemoryMemory()
        self._context_factory = context or SlidingWindowContext()
        self._max_steps = max_steps
        self.hooks = hooks or HookManager()
        self._checkpoint_store = checkpoint_store
        if (
            checkpoint_identity is not None
            and not checkpoint_identity.strip()
        ):
            raise ValueError("checkpoint_identity must not be blank")
        self._checkpoint_identity = (
            checkpoint_identity.strip()
            if checkpoint_identity is not None
            else f"{type(self).__module__}.{type(self).__qualname__}"
        )
        self._log = Logger(self.__class__.__name__)
        # Respect class-level ``session_class`` declarations on subclasses
        # (e.g. ``class GroupChatAgent(ReactAgent): session_class = GroupChatSession``).
        # Only the explicit kwarg or a class-level override should win — never
        # silently fall back to plain ``AgentSession`` when a subclass declared one.
        self.session_class = session_class or type(self).session_class or AgentSession

    @property
    def default_model(self) -> BaseLLM:
        return self._default_model

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def checkpoint_identity(self) -> str:
        return self._checkpoint_identity

    # ── session factory ──────────────────────────────────────────────────

    def create_session(
        self,
        *,
        memory: BaseMemory | None = None,
        context: BaseContext | None = None,
        session_id: str | None = None,
        checkpoint_store: CheckpointStore | None = None,
    ) -> AgentSession:
        return self.session_class(
            session_id=session_id or uuid.uuid4().hex,
            agent=self,
            memory=memory or self._memory_factory.clone(),
            context=context or self._context_factory.clone(),
            checkpoint_store=(
                checkpoint_store
                if checkpoint_store is not None
                else self._checkpoint_store
            ),
        )

    def check_checkpoint(
        self,
        checkpoint: AgentCheckpoint,
    ) -> CheckpointCompatibilityReport:
        """Check whether this Agent can safely interpret a checkpoint."""
        issues: list[CheckpointCompatibilityIssue] = []
        if checkpoint.agent_identity != self.checkpoint_identity:
            issues.append(
                CheckpointCompatibilityIssue(
                    code="agent_identity_mismatch",
                    message=(
                        "Agent identity mismatch: "
                        f"checkpoint='{checkpoint.agent_identity}', "
                        f"current='{self.checkpoint_identity}'"
                    ),
                    checkpoint_value=checkpoint.agent_identity,
                    current_value=self.checkpoint_identity,
                )
            )
        if (
            checkpoint.agent_name
            and checkpoint.agent_name != self.name
        ):
            issues.append(
                CheckpointCompatibilityIssue(
                    code="agent_name_mismatch",
                    message=(
                        "Agent name mismatch: "
                        f"checkpoint='{checkpoint.agent_name}', "
                        f"current='{self.name}'"
                    ),
                    checkpoint_value=checkpoint.agent_name,
                    current_value=self.name,
                )
            )
        return CheckpointCompatibilityReport(issues=tuple(issues))

    def restore_session(
        self,
        checkpoint: AgentCheckpoint,
        *,
        checkpoint_store: CheckpointStore | None = None,
    ) -> AgentSession:
        """Rebuild Session state without starting or continuing execution."""
        report = self.check_checkpoint(checkpoint)
        if not report.compatible:
            raise IncompatibleCheckpointError(report)
        if not checkpoint.session_id.strip():
            raise InvalidCheckpointStateError(checkpoint.session_id)
        try:
            checkpoint.to_dict()
            restored_status = AgentStatus(checkpoint.status)
            restored_messages = [
                Message.model_validate(deepcopy(message))
                for message in checkpoint.messages
            ]
            restored_steps: list[LoopStepResult] = []
            for step in checkpoint.loop_steps:
                output = step.get("output")
                if output is not None and not isinstance(output, str):
                    raise TypeError(
                        "Checkpoint step output must be text or null"
                    )
                restored_steps.append(
                    LoopStepResult(
                        status=StepStatus(step["status"]),
                        output=output,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCheckpointStateError(
                checkpoint.session_id
            ) from exc
        session = self.create_session(
            session_id=checkpoint.session_id,
            checkpoint_store=checkpoint_store,
        )
        assert session.memory is not None
        session.memory.clear()
        for message in restored_messages:
            session.add_message(message)
        session.status = restored_status
        session.iteration_count = checkpoint.iteration_count
        session.final_output = checkpoint.final_output
        session.loop_steps = restored_steps
        session.enabled_tools = list(checkpoint.enabled_tools)
        session.loaded_skills = list(checkpoint.loaded_skills)
        session.metadata = deepcopy(checkpoint.metadata)
        session.loop_state = deepcopy(checkpoint.loop_state)
        session._mark_restored_from_checkpoint()
        return session

    # ── run lifecycle ────────────────────────────────────────────────────

    async def run(
        self,
        user_input: Any,
        *,
        session: AgentSession | None = None,
        event_bus: EventBus | None = None,
    ) -> AgentRunResult:
        active_session = session or self.create_session()
        await active_session.run(user_input, event_bus=event_bus)
        return AgentRunResult.from_session(active_session)

    async def on_session_start(self, session: AgentSession) -> None:
        """Called before the first step. Subclasses override for setup."""

    async def on_session_end(self, session: AgentSession) -> None:
        """Called after the last step (even on error). Subclasses override for cleanup."""

    async def run_session(self, session: AgentSession, user_input: Any) -> str:
        if isinstance(user_input, Message):
            session.add_message(user_input)
        else:
            session.add_message(Message.user(user_input))
        return await self.run_prepared_session(session)

    async def run_prepared_session(self, session: AgentSession) -> str:
        """Execute a run whose input messages are already in session memory."""
        session.iteration_count = 0
        session.loop_steps.clear()
        session.loop_state.clear()
        result = await self.step(session)
        await session._record_step(result)
        while not result.done:
            result = await self.step(session)
            await session._record_step(result)
        return result.output or session.final_output or ""

    async def resume_session(self, session: AgentSession) -> str:
        """Continue from restored loop state without resetting bookkeeping."""
        result = session.loop_steps[-1] if session.loop_steps else None
        if result is not None and result.done:
            return (
                result.output
                if result.output is not None
                else session.final_output or ""
            )
        result = await self.step(session)
        await session._record_step(result)
        while not result.done:
            result = await self.step(session)
            await session._record_step(result)
        return (
            result.output
            if result.output is not None
            else session.final_output or ""
        )

    async def stream(
        self,
        user_input: Any,
        *,
        session: AgentSession | None = None,
        event_bus: EventBus | None = None,
    ) -> AsyncIterator[str]:
        active_session = session or self.create_session()
        session_stream = active_session.stream(user_input, event_bus=event_bus)
        try:
            async for chunk in session_stream:
                yield chunk
        finally:
            await session_stream.aclose()

    async def stream_session(
        self,
        session: AgentSession,
        user_input: Any,
    ) -> AsyncIterator[str]:
        if isinstance(user_input, Message):
            session.add_message(user_input)
        else:
            session.add_message(Message.user(user_input))
        session.iteration_count = 0
        session.loop_steps.clear()
        session.loop_state.clear()

        early_exit = self._consume_stop_request(session)
        if early_exit is not None:
            await session._record_step(early_exit)
            if early_exit.output:
                yield early_exit.output
            return

        messages = await session.get_model_messages(self.build_system_prompt(session))
        response = None
        await self._emit_llm_called(session, messages)
        stream_sequence = 0
        emitted_text = False
        async for chunk in self.default_model.call_with_history_stream(messages):
            if chunk.content:
                stream_sequence += 1
                await self._emit_llm_stream_chunk(session, chunk.content, stream_sequence)
                emitted_text = True
                yield chunk.content
            if chunk.done:
                response = chunk.response

        if response is None:
            response = await self.default_model.call_with_history(messages)
        await self._emit_llm_responded(session, response)
        early_exit = self._consume_stop_request(session)
        if early_exit is not None:
            await session._record_step(early_exit)
            if not emitted_text and early_exit.output:
                yield early_exit.output
            return
        session.add_message(Message.from_response(response))
        session.final_output = response.content
        session.loop_state["plain_agent_done"] = True
        result = LoopStepResult(status=StepStatus.COMPLETED, output=response.content)
        await session._record_step(result)

    # ── single step ──────────────────────────────────────────────────────

    async def step(
        self,
        session: AgentSession,
    ) -> LoopStepResult:
        early_exit = self._consume_stop_request(session)
        if early_exit is not None:
            return early_exit
        if session.loop_state.get("plain_agent_done"):
            return LoopStepResult(status=StepStatus.COMPLETED, output=session.final_output)
        messages = await session.get_model_messages(self.build_system_prompt(session))
        await self._emit_llm_called(session, messages)
        response = await self.default_model.call_with_history(messages)
        await self._emit_llm_responded(session, response)
        early_exit = self._consume_stop_request(session)
        if early_exit is not None:
            return early_exit
        session.add_message(Message.from_response(response))
        session.final_output = response.content
        session.loop_state["plain_agent_done"] = True
        return LoopStepResult(status=StepStatus.COMPLETED, output=response.content)

    @staticmethod
    def _consume_stop_request(
        session: AgentSession,
    ) -> LoopStepResult | None:
        return session._consume_stop_request()

    async def _emit_llm_called(
        self,
        session: AgentSession,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        if not session.event_bus:
            return
        from easyagent.events import LLMCalledEvent

        model_name = getattr(self.default_model, "model", "") or getattr(self.default_model, "_model", "")
        serialized_messages = serialize_messages(messages or [])
        await session.event_bus.publish(
            LLMCalledEvent(
                agent_id=session.session_id,
                model=model_name,
                message_count=len(serialized_messages),
                messages=serialized_messages,
            )
        )

    async def _emit_llm_responded(self, session: AgentSession, response: Any) -> None:
        if not session.event_bus:
            return
        from easyagent.events import LLMRespondedEvent

        model_name = getattr(self.default_model, "model", "") or getattr(self.default_model, "_model", "")
        await session.event_bus.publish(
            LLMRespondedEvent(
                agent_id=session.session_id,
                model=model_name,
                content=response.content,
                tool_calls=serialize_tool_calls(response),
                usage=response.usage or {},
            )
        )

    async def _emit_llm_stream_chunk(self, session: AgentSession, content: str, sequence: int) -> None:
        if not session.event_bus:
            return
        from easyagent.events import LLMStreamChunkEvent

        model_name = getattr(self.default_model, "model", "") or getattr(self.default_model, "_model", "")
        await session.event_bus.publish(
            LLMStreamChunkEvent(
                agent_id=session.session_id,
                model=model_name,
                content=content,
                sequence=sequence,
            )
        )

    # ── extension points for subclasses ──────────────────────────────────

    def build_system_prompt(self, session: AgentSession) -> str:
        return self._system_prompt

    def get_tool_schemas(self, session: AgentSession) -> list[dict[str, Any]]:
        return []

    async def execute_tool_call(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        return f"Tool '{name}' not available"
