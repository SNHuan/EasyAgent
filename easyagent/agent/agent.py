from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator

from easyagent.agent.base import BaseAgent
from easyagent.agent.session import AgentRunResult, AgentSession, AgentStatus, LoopStepResult, StepStatus
from easyagent.context.base import BaseContext
from easyagent.context.sliding import SlidingWindowContext
from easyagent.debug.log import Logger
from easyagent.memory.base import BaseMemory
from easyagent.memory.inmemory import InMemoryMemory
from easyagent.model.base import BaseLLM
from easyagent.model.schema import Message

if TYPE_CHECKING:
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
    ):
        self._default_model = model
        self._system_prompt = system_prompt
        self.name = name
        self.description = description
        self._memory_factory = memory or InMemoryMemory()
        self._context_factory = context or SlidingWindowContext()
        self._max_steps = max_steps
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

    # ── session factory ──────────────────────────────────────────────────

    def create_session(
        self,
        *,
        memory: BaseMemory | None = None,
        context: BaseContext | None = None,
        session_id: str | None = None,
    ) -> AgentSession:
        return self.session_class(
            session_id=session_id or uuid.uuid4().hex,
            agent=self,
            memory=memory or self._memory_factory.clone(),
            context=context or self._context_factory.clone(),
        )

    # ── run lifecycle ────────────────────────────────────────────────────

    async def run(
        self,
        user_input: Any,
        *,
        session: AgentSession | None = None,
        event_bus: EventBus | None = None,
    ) -> AgentRunResult:
        active_session = session or self.create_session()
        if event_bus is not None:
            active_session.event_bus = event_bus
        bus = active_session.event_bus
        active_session.status = AgentStatus.RUNNING
        if bus is not None:
            from easyagent.events import AgentStartedEvent

            await bus.publish(AgentStartedEvent(agent_id=active_session.session_id))
        await self.on_session_start(active_session)
        try:
            result = await self.run_session(active_session, user_input)
        except Exception as exc:
            active_session.status = AgentStatus.FAILED
            if bus is not None:
                from easyagent.events import AgentFailedEvent

                await bus.publish(
                    AgentFailedEvent(
                        agent_id=active_session.session_id,
                        error=str(exc),
                        messages=_serialize_session_messages(active_session.get_all_messages()),
                    )
                )
            raise
        finally:
            await self.on_session_end(active_session)
        active_session.final_output = result
        active_session.status = AgentStatus.COMPLETED
        if bus is not None:
            from easyagent.events import AgentFinishedEvent

            await bus.publish(
                AgentFinishedEvent(
                    agent_id=active_session.session_id,
                    output=result,
                    messages=_serialize_session_messages(active_session.get_all_messages()),
                )
            )
        return AgentRunResult.from_session(active_session)

    async def on_session_start(self, session: AgentSession) -> None:
        """Called before the first step. Subclasses override for setup."""

    async def on_session_end(self, session: AgentSession) -> None:
        """Called after the last step (even on error). Subclasses override for cleanup."""

    async def run_session(self, session: AgentSession, user_input: Any) -> str:
        session.add_message(Message.user(user_input))
        session.iteration_count = 0
        session.loop_steps.clear()
        session.loop_state.clear()
        result = await self.step(session)
        session.loop_steps.append(result)
        while not result.done:
            result = await self.step(session)
            session.loop_steps.append(result)
        return result.output or session.final_output or ""

    async def stream(
        self,
        user_input: Any,
        *,
        session: AgentSession | None = None,
        event_bus: EventBus | None = None,
    ) -> AsyncIterator[str]:
        active_session = session or self.create_session()
        if event_bus is not None:
            active_session.event_bus = event_bus
        bus = active_session.event_bus
        active_session.status = AgentStatus.RUNNING
        if bus is not None:
            from easyagent.events import AgentStartedEvent

            await bus.publish(AgentStartedEvent(agent_id=active_session.session_id))
        await self.on_session_start(active_session)
        try:
            async for chunk in self.stream_session(active_session, user_input):
                yield chunk
        except Exception as exc:
            active_session.status = AgentStatus.FAILED
            if bus is not None:
                from easyagent.events import AgentFailedEvent

                await bus.publish(
                    AgentFailedEvent(
                        agent_id=active_session.session_id,
                        error=str(exc),
                        messages=_serialize_session_messages(active_session.get_all_messages()),
                    )
                )
            raise
        finally:
            await self.on_session_end(active_session)

        active_session.status = AgentStatus.COMPLETED
        if bus is not None:
            from easyagent.events import AgentFinishedEvent

            await bus.publish(
                AgentFinishedEvent(
                    agent_id=active_session.session_id,
                    output=active_session.final_output or "",
                    messages=_serialize_session_messages(active_session.get_all_messages()),
                )
            )

    async def stream_session(
        self,
        session: AgentSession,
        user_input: Any,
    ) -> AsyncIterator[str]:
        session.add_message(Message.user(user_input))
        session.iteration_count = 0
        session.loop_steps.clear()
        session.loop_state.clear()

        messages = await session.get_model_messages(self.build_system_prompt(session))
        response = None
        await self._emit_llm_called(session, messages)
        async for chunk in self.default_model.call_with_history_stream(messages):
            if chunk.content:
                yield chunk.content
            if chunk.done:
                response = chunk.response

        if response is None:
            response = await self.default_model.call_with_history(messages)
        await self._emit_llm_responded(session, response)
        session.add_message(Message.from_response(response))
        session.final_output = response.content
        session.loop_state["plain_agent_done"] = True
        result = LoopStepResult(status=StepStatus.COMPLETED, output=response.content)
        session.loop_steps.append(result)

    # ── single step ──────────────────────────────────────────────────────

    async def step(
        self,
        session: AgentSession,
    ) -> LoopStepResult:
        if session.loop_state.get("plain_agent_done"):
            return LoopStepResult(status=StepStatus.COMPLETED, output=session.final_output)
        messages = await session.get_model_messages(self.build_system_prompt(session))
        await self._emit_llm_called(session, messages)
        response = await self.default_model.call_with_history(messages)
        await self._emit_llm_responded(session, response)
        session.add_message(Message.from_response(response))
        session.final_output = response.content
        session.loop_state["plain_agent_done"] = True
        return LoopStepResult(status=StepStatus.COMPLETED, output=response.content)

    async def _emit_llm_called(
        self,
        session: AgentSession,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        if not session.event_bus:
            return
        from easyagent.events import LLMCalledEvent

        model_name = getattr(self.default_model, "model", "") or getattr(self.default_model, "_model", "")
        serialized_messages = _serialize_messages(messages or [])
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
                tool_calls=_serialize_tool_calls(response),
                usage=response.usage or {},
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


def _serialize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {}
        for key, value in message.items():
            if key == "content":
                item[key] = _truncate_message_content(value)
            else:
                item[key] = value
        serialized.append(item)
    return serialized


def _truncate_message_content(content: Any) -> Any:
    if isinstance(content, str):
        return content if len(content) <= 8_000 else f"{content[:8_000]}... [truncated]"
    if isinstance(content, list):
        return [_truncate_message_content(item) for item in content]
    if isinstance(content, dict):
        return {str(key): _truncate_message_content(value) for key, value in content.items()}
    return content


def _serialize_session_messages(messages: list[Message]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for message in messages:
        data = message.model_dump(exclude_none=True)
        if "content" in data:
            data["content"] = _truncate_message_content(data["content"])
        serialized.append(data)
    return serialized


def _serialize_tool_calls(response: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(response, "tool_calls", None) or []
    serialized: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if hasattr(tool_call, "model_dump"):
            serialized.append(tool_call.model_dump())
        elif isinstance(tool_call, dict):
            serialized.append(tool_call)
    return serialized
