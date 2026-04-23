from __future__ import annotations

from typing import Any

from easyagent.agent.base import BaseAgent
from easyagent.agent.session import AgentSession, AgentStatus
from easyagent.context.base import BaseContext
from easyagent.context.sliding import SlidingWindowContext
from easyagent.debug.log import Logger
from easyagent.loop.base import BaseLoop
from easyagent.memory.base import BaseMemory
from easyagent.memory.inmemory import InMemoryMemory
from easyagent.model.base import BaseLLM


class Agent(BaseAgent):
    def __init__(
        self,
        model: BaseLLM,
        loop: BaseLoop,
        *,
        memory: BaseMemory | None = None,
        context: BaseContext | None = None,
        system_prompt: str = "",
        default_tools: list[str] | None = None,
        capabilities: list[Any] | None = None,
    ):
        super().__init__(default_model=model, system_prompt=system_prompt)
        self._loop = loop
        self._memory_template = memory or InMemoryMemory()
        self._context_template = context or SlidingWindowContext()
        self._default_tools = list(default_tools or [])
        self._capabilities = list(capabilities or [])
        self._log = Logger(self.__class__.__name__)
        for capability in self._capabilities:
            on_attach = getattr(capability, "on_attach", None)
            if on_attach is not None:
                on_attach(self)

    @property
    def loop(self) -> BaseLoop:
        return self._loop

    def create_session(
        self,
        *,
        model: BaseLLM | None = None,
        memory: BaseMemory | None = None,
        context: BaseContext | None = None,
    ) -> AgentSession:
        return AgentSession(
            current_model=model or self.default_model,
            memory=memory or self._memory_template.clone(),
            context=context or self._context_template.clone(),
            enabled_tools=list(self._default_tools),
        )

    async def run(self, user_input: Any, *, session: AgentSession | None = None) -> str:
        active_session = session or self.create_session()
        active_session.status = AgentStatus.RUNNING
        try:
            for capability in self._capabilities:
                on_enter = getattr(capability, "on_enter", None)
                if on_enter is not None:
                    await on_enter(self, active_session)
            result = await self._loop.run(self, active_session, user_input)
        except Exception:
            active_session.status = AgentStatus.FAILED
            raise
        finally:
            for capability in reversed(self._capabilities):
                on_exit = getattr(capability, "on_exit", None)
                if on_exit is not None:
                    await on_exit(self, active_session)
        active_session.final_output = result
        active_session.status = AgentStatus.COMPLETED
        return result

    async def get_model_messages(self, session: AgentSession) -> list[dict[str, Any]]:
        return await session.get_model_messages(self.build_system_prompt(session))

    def build_system_prompt(self, session: AgentSession) -> str:
        parts = [self.system_prompt]
        for capability in self._capabilities:
            getter = getattr(capability, "get_system_prompt_parts", None)
            if getter is None:
                continue
            parts.extend(getter(self, session) or [])
        return "\n\n".join(part for part in parts if part)

    def get_tool_schemas(self, session: AgentSession) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for capability in self._capabilities:
            getter = getattr(capability, "get_tool_schemas", None)
            if getter is None:
                continue
            schemas.extend(getter(self, session) or [])
        return schemas

    async def execute_tool_call(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        for capability in self._capabilities:
            handler = getattr(capability, "handle_tool_call", None)
            if handler is None:
                continue
            result = await handler(self, session, name, arguments)
            if result is not None:
                return result
        return f"Tool '{name}' not available"
