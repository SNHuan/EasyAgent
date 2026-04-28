from __future__ import annotations

import uuid
from typing import Any

from easyagent.agent.base import BaseAgent
from easyagent.agent.session import AgentRunResult, AgentSession, AgentStatus, LoopStepResult, StepStatus
from easyagent.context.base import BaseContext
from easyagent.context.sliding import SlidingWindowContext
from easyagent.debug.log import Logger
from easyagent.memory.base import BaseMemory
from easyagent.memory.inmemory import InMemoryMemory
from easyagent.model.base import BaseLLM
from easyagent.model.schema import Message


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

    async def run(self, user_input: Any, *, session: AgentSession | None = None) -> AgentRunResult:
        active_session = session or self.create_session()
        active_session.status = AgentStatus.RUNNING
        await self.on_session_start(active_session)
        try:
            result = await self.run_session(active_session, user_input)
        except Exception:
            active_session.status = AgentStatus.FAILED
            raise
        finally:
            await self.on_session_end(active_session)
        active_session.final_output = result
        active_session.status = AgentStatus.COMPLETED
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

    # ── single step ──────────────────────────────────────────────────────

    async def step(
        self,
        session: AgentSession,
    ) -> LoopStepResult:
        if session.loop_state.get("plain_agent_done"):
            return LoopStepResult(status=StepStatus.COMPLETED, output=session.final_output)
        messages = await session.get_model_messages(self.build_system_prompt(session))
        response = await self.default_model.call_with_history(messages)
        session.add_message(Message.from_response(response))
        session.final_output = response.content
        session.loop_state["plain_agent_done"] = True
        return LoopStepResult(status=StepStatus.COMPLETED, output=response.content)

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
