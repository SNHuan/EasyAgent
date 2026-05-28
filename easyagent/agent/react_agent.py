from __future__ import annotations

import json
from inspect import Parameter, iscoroutinefunction, signature
from typing import Any, AsyncIterator

from easyagent.agent.agent import Agent
from easyagent.agent.session import AgentSession, LoopStepResult, StepStatus
from easyagent.config.base import is_debug
from easyagent.debug.log import Color
from easyagent.model.schema import Message, content_to_text
from easyagent.prompt.react import REACT_SYSTEM_PROMPT
from easyagent.tool import ToolManager


class ReactAgent(Agent):
    """Agent with tool calling and a ReAct execution loop.

    This is the primary agent for multi-step tasks. It runs a
    Reason-Act loop: call the LLM, execute any tool calls, repeat
    until the model returns a plain assistant message with no tool calls
    or ``max_iterations`` is reached.
    """

    def __init__(
        self,
        model: Any,
        *,
        tools: list[Any] | None = None,
        tool_manager: ToolManager | None = None,
        max_iterations: int = 10,
        **kwargs: Any,
    ):
        super().__init__(model, max_steps=max_iterations, **kwargs)
        self._tool_manager = tool_manager or ToolManager(discover_builtin=False)
        self._enabled_tool_names: list[str] = []
        for t in tools or []:
            self.add_tool(t)

    def add_tool(self, tool: Any, *, enabled: bool = True) -> None:
        tools = tool if isinstance(tool, list) else [tool]
        for t in tools:
            registered_tool = t() if isinstance(t, type) else t
            self._tool_manager.register(registered_tool)
            if enabled and registered_tool.name not in self._enabled_tool_names:
                self._enabled_tool_names.append(registered_tool.name)

    def create_session(self, **kwargs: Any) -> AgentSession:
        session = super().create_session(**kwargs)
        session.enabled_tools = list(self._enabled_tool_names)
        return session

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def run_session(self, session: AgentSession, user_input: Any) -> str:
        if is_debug():
            label = self._agent_label(session)
            self._log.debug(f"[{label}] {content_to_text(user_input)}")
        return await super().run_session(session, user_input)

    async def stream_session(
        self,
        session: AgentSession,
        user_input: Any,
    ) -> AsyncIterator[str]:
        if is_debug():
            label = self._agent_label(session)
            self._log.debug(f"[{label}] {content_to_text(user_input)}")

        session.add_message(Message.user(user_input))
        session.iteration_count = 0
        session.loop_steps.clear()
        session.loop_state.clear()

        while True:
            async for chunk in self._stream_step_chunks(session):
                yield chunk
            result = session.loop_state.pop("_stream_step_result")
            session.loop_steps.append(result)
            if result.done:
                break

        if result.output:
            session.final_output = result.output

    async def _stream_step_chunks(self, session: AgentSession) -> AsyncIterator[str]:
        label = self._agent_label(session)

        if session.iteration_count >= self._max_steps:
            self._set_stream_step_result(
                session,
                LoopStepResult(status=StepStatus.MAX_ITERATIONS, output=session.final_output),
            )
            return

        session.iteration_count += 1
        if is_debug():
            self._log.debug(f"[{label}] Iteration {session.iteration_count}/{self._max_steps}")

        messages = await session.get_model_messages(self.build_system_prompt(session))
        tool_schemas = self.get_tool_schemas(session)
        llm_kwargs: dict[str, Any] = {"tools": tool_schemas} if tool_schemas else {}

        await self._emit_llm_called(session, messages)
        response = None
        emitted_text = False
        stream_sequence = 0
        async for chunk in self.default_model.call_with_history_stream(messages, **llm_kwargs):
            if chunk.content:
                stream_sequence += 1
                await self._emit_llm_stream_chunk(session, chunk.content, stream_sequence)
                emitted_text = True
                if is_debug():
                    self._log.info(f"[{label}] {chunk.content}", color=Color.GRAY)
                yield chunk.content
            if chunk.done:
                response = chunk.response

        if response is None:
            response = await self.default_model.call_with_history(messages, **llm_kwargs)

        await self._emit_llm_responded(session, response)

        if not response.tool_calls:
            session.add_message(Message.assistant(response.content))
            session.final_output = response.content
            self._set_stream_step_result(
                session,
                LoopStepResult(status=StepStatus.COMPLETED, output=response.content),
            )
            return

        session.add_message(
            Message.assistant(response.content, _format_tool_calls(response.tool_calls))
        )

        for tool_call in response.tool_calls:
            if is_debug():
                self._log.info(
                    f"[{label}] Tool call {tool_call.name}({tool_call.arguments})",
                    color=Color.YELLOW,
                )
            await self._emit_tool_called(session, tool_call)

            result = await self.execute_tool_call(session, tool_call.name, tool_call.arguments)

            if is_debug():
                self._log.info(f"[{label}] Tool result: {result}", color=Color.GREEN)
            await self._emit_tool_result(session, tool_call.name, result)

            session.add_message(Message.tool(result, tool_call.id))

            if "__early_exit__" in session.loop_state:
                payload = session.loop_state.pop("__early_exit__")
                final_text = payload if isinstance(payload, str) else str(payload)
                session.final_output = final_text
                if is_debug():
                    self._log.info(f"[{label}] early-exit: {final_text}", color=Color.CYAN)
                if not emitted_text and final_text:
                    yield final_text
                self._set_stream_step_result(
                    session,
                    LoopStepResult(status=StepStatus.EARLY_EXIT, output=final_text),
                )
                return

        self._set_stream_step_result(session, LoopStepResult(status=StepStatus.CONTINUE))

    @staticmethod
    def _set_stream_step_result(session: AgentSession, result: LoopStepResult) -> None:
        session.loop_state["_stream_step_result"] = result

    # ── ReAct step ───────────────────────────────────────────────────────

    async def step(
        self,
        session: AgentSession,
    ) -> LoopStepResult:
        label = self._agent_label(session)

        if session.iteration_count >= self._max_steps:
            return LoopStepResult(status=StepStatus.MAX_ITERATIONS, output=session.final_output)

        session.iteration_count += 1
        if is_debug():
            self._log.debug(f"[{label}] Iteration {session.iteration_count}/{self._max_steps}")

        messages = await session.get_model_messages(self.build_system_prompt(session))
        tool_schemas = self.get_tool_schemas(session)
        llm_kwargs: dict[str, Any] = {"tools": tool_schemas} if tool_schemas else {}

        await self._emit_llm_called(session, messages)
        response = await self.default_model.call_with_history(messages, **llm_kwargs)
        await self._emit_llm_responded(session, response)

        if is_debug() and response.content:
            self._log.info(f"[{label}] {response.content}", color=Color.GRAY)

        if not response.tool_calls:
            session.add_message(Message.assistant(response.content))
            session.final_output = response.content
            return LoopStepResult(status=StepStatus.COMPLETED, output=response.content)

        session.add_message(
            Message.assistant(response.content, _format_tool_calls(response.tool_calls))
        )

        for tool_call in response.tool_calls:
            if is_debug():
                self._log.info(
                    f"[{label}] Tool call {tool_call.name}({tool_call.arguments})",
                    color=Color.YELLOW,
                )
            await self._emit_tool_called(session, tool_call)

            result = await self.execute_tool_call(session, tool_call.name, tool_call.arguments)

            if is_debug():
                self._log.info(f"[{label}] Tool result: {result}", color=Color.GREEN)
            await self._emit_tool_result(session, tool_call.name, result)

            session.add_message(Message.tool(result, tool_call.id))

            if "__early_exit__" in session.loop_state:
                payload = session.loop_state.pop("__early_exit__")
                final_text = payload if isinstance(payload, str) else str(payload)
                session.final_output = final_text
                if is_debug():
                    self._log.info(f"[{label}] early-exit: {final_text}", color=Color.CYAN)
                return LoopStepResult(status=StepStatus.EARLY_EXIT, output=final_text)

        return LoopStepResult(status=StepStatus.CONTINUE)

    # ── extension points ─────────────────────────────────────────────────

    def build_system_prompt(self, session: AgentSession) -> str:
        base = super().build_system_prompt(session)
        if base:
            return "\n\n".join([REACT_SYSTEM_PROMPT, base])
        return REACT_SYSTEM_PROMPT

    def get_tool_schemas(self, session: AgentSession) -> list[dict[str, Any]]:
        return self._tool_manager.get_schema(session.enabled_tools)

    async def execute_tool_call(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        if name not in session.enabled_tools:
            return f"Tool '{name}' is not enabled"
        tool = self._tool_manager.get(name)
        if tool is None:
            return f"Tool '{name}' not found"
        call_kwargs = _bind_execute_kwargs(tool.execute, arguments, session)
        if iscoroutinefunction(tool.execute):
            return await tool.execute(**call_kwargs)
        return tool.execute(**call_kwargs)

    # ── internals ────────────────────────────────────────────────────────

    def _agent_label(self, session: AgentSession) -> str:
        return session.session_id.strip() or self.name.strip() or self.__class__.__name__

    # ── telemetry (optional, only emits when event_bus is present) ───────

    async def _emit_llm_called(
        self,
        session: AgentSession,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        if not session.event_bus:
            return
        from easyagent.events.types import LLMCalledEvent
        from easyagent.agent.agent import _serialize_messages

        model_name = getattr(self.default_model, "model", "") or getattr(self.default_model, "_model", "")
        serialized_messages = _serialize_messages(messages or [])
        await session.event_bus.publish(LLMCalledEvent(
            agent_id=session.session_id,
            model=model_name,
            message_count=len(serialized_messages),
            messages=serialized_messages,
        ))

    async def _emit_llm_responded(self, session: AgentSession, response: Any) -> None:
        if not session.event_bus:
            return
        from easyagent.events.types import LLMRespondedEvent
        from easyagent.agent.agent import _serialize_tool_calls

        model_name = getattr(self.default_model, "model", "") or getattr(self.default_model, "_model", "")
        await session.event_bus.publish(LLMRespondedEvent(
            agent_id=session.session_id,
            model=model_name,
            content=response.content,
            tool_calls=_serialize_tool_calls(response),
            usage=response.usage or {},
        ))

    async def _emit_llm_stream_chunk(self, session: AgentSession, content: str, sequence: int) -> None:
        if not session.event_bus:
            return
        from easyagent.events.types import LLMStreamChunkEvent

        model_name = getattr(self.default_model, "model", "") or getattr(self.default_model, "_model", "")
        await session.event_bus.publish(LLMStreamChunkEvent(
            agent_id=session.session_id,
            model=model_name,
            content=content,
            sequence=sequence,
        ))

    async def _emit_tool_called(self, session: AgentSession, tool_call: Any) -> None:
        if not session.event_bus:
            return
        from easyagent.events.types import ToolCalledEvent

        await session.event_bus.publish(ToolCalledEvent(
            agent_id=session.session_id,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
        ))

    async def _emit_tool_result(self, session: AgentSession, tool_name: str, result: str) -> None:
        if not session.event_bus:
            return
        from easyagent.events.types import ToolResultEvent

        await session.event_bus.publish(ToolResultEvent(
            agent_id=session.session_id,
            tool_name=tool_name,
            result=result,
        ))


def _format_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": tc.id,
            "type": tc.type,
            "function": {
                "name": tc.name,
                "arguments": json.dumps(tc.arguments),
            },
        }
        for tc in tool_calls
    ]


def _bind_execute_kwargs(func: Any, arguments: dict[str, Any], session: Any) -> dict[str, Any]:
    sig = signature(func)
    params = sig.parameters
    bound = {k.strip().rstrip(":").strip(): v for k, v in arguments.items()}

    if "session" in params:
        bound["session"] = session
        return bound

    if any(param.kind == Parameter.VAR_KEYWORD for param in params.values()):
        bound["session"] = session
    return bound
