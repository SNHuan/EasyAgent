from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, AsyncIterator

from easyagent.agent.session import AgentSession, LoopStepResult, StepStatus
from easyagent.agent.serialization import serialize_messages, serialize_tool_calls
from easyagent.config.base import is_debug
from easyagent.debug.log import Color, Logger
from easyagent.events import (
    LLMCalledEvent,
    LLMRespondedEvent,
    LLMStreamChunkEvent,
    ToolCalledEvent,
    ToolResultEvent,
)
from easyagent.model.schema import LLMResponse, Message
from easyagent.tool import ToolResult

ToolSchemaProvider = Callable[[AgentSession], list[dict[str, Any]]]
ModelProvider = Callable[[], Any]
ToolExecutor = Callable[
    [AgentSession, str, dict[str, Any]],
    Awaitable[ToolResult],
]


@dataclass(frozen=True, slots=True)
class RunEngineUpdate:
    """One streamed chunk or the terminal result of a single agent step."""

    chunk: str | None = None
    step_result: LoopStepResult | None = None

    def __post_init__(self) -> None:
        if (self.chunk is None) == (self.step_result is None):
            raise ValueError(
                "RunEngineUpdate requires exactly one of chunk or step_result"
            )


class ReactRunEngine:
    """Execute one complete ReAct state transition.

    Streaming and non-streaming calls share the same response, tool, Hook,
    Event, memory, and stop handling. The only mode-specific branch is how the
    model response is obtained and whether text chunks are exposed.
    """

    def __init__(
        self,
        *,
        get_model: ModelProvider,
        get_tool_schemas: ToolSchemaProvider,
        execute_tool_call: ToolExecutor,
        max_steps: int,
        logger: Logger,
    ) -> None:
        self._get_model = get_model
        self._get_tool_schemas = get_tool_schemas
        self._execute_tool_call = execute_tool_call
        self._max_steps = max_steps
        self._log = logger

    async def execute_step(
        self,
        session: AgentSession,
        system_prompt: str,
        *,
        stream: bool,
    ) -> AsyncIterator[RunEngineUpdate]:
        label = self._agent_label(session)
        early_exit = session._consume_stop_request()
        if early_exit is not None:
            if stream and early_exit.output:
                yield RunEngineUpdate(chunk=early_exit.output)
            yield RunEngineUpdate(step_result=early_exit)
            return

        if session.iteration_count >= self._max_steps:
            yield RunEngineUpdate(
                step_result=LoopStepResult(
                    status=StepStatus.MAX_ITERATIONS,
                    output=session.final_output,
                )
            )
            return

        model = self._get_model()
        session.iteration_count += 1
        if is_debug():
            self._log.debug(
                f"[{label}] Iteration "
                f"{session.iteration_count}/{self._max_steps}"
            )

        messages = await session.get_model_messages(system_prompt)
        tool_schemas = self._get_tool_schemas(session)
        llm_kwargs: dict[str, Any] = {"tools": tool_schemas} if tool_schemas else {}
        await self._emit_llm_called(session, model, messages)

        response: LLMResponse | None = None
        emitted_text = False
        if stream:
            stream_sequence = 0
            async for chunk in model.call_with_history_stream(
                messages,
                **llm_kwargs,
            ):
                if chunk.content:
                    stream_sequence += 1
                    await self._emit_llm_stream_chunk(
                        session,
                        model,
                        chunk.content,
                        stream_sequence,
                    )
                    emitted_text = True
                    if is_debug():
                        self._log.info(
                            f"[{label}] {chunk.content}",
                            color=Color.GRAY,
                        )
                    yield RunEngineUpdate(chunk=chunk.content)
                if chunk.done:
                    response = chunk.response
        else:
            response = await model.call_with_history(
                messages,
                **llm_kwargs,
            )

        if response is None:
            response = await model.call_with_history(
                messages,
                **llm_kwargs,
            )
        await self._emit_llm_responded(session, model, response)

        early_exit = session._consume_stop_request()
        if early_exit is not None:
            if stream and not emitted_text and early_exit.output:
                yield RunEngineUpdate(chunk=early_exit.output)
            yield RunEngineUpdate(step_result=early_exit)
            return

        if not stream and is_debug() and response.content:
            self._log.info(f"[{label}] {response.content}", color=Color.GRAY)

        if not response.tool_calls:
            session.add_message(Message.assistant(response.content))
            session.final_output = response.content
            yield RunEngineUpdate(
                step_result=LoopStepResult(
                    status=StepStatus.COMPLETED,
                    output=response.content,
                )
            )
            return

        session.add_message(
            Message.assistant(
                response.content,
                _format_tool_calls(response.tool_calls),
            )
        )

        for tool_call in response.tool_calls:
            if is_debug():
                self._log.info(
                    f"[{label}] Tool call "
                    f"{tool_call.name}({tool_call.arguments})",
                    color=Color.YELLOW,
                )
            await self._emit_tool_called(session, tool_call.name, tool_call.arguments)
            tool_result = await self._execute_tool_call(
                session,
                tool_call.name,
                tool_call.arguments,
            )
            if is_debug():
                self._log.info(
                    f"[{label}] Tool result: {tool_result.content}",
                    color=Color.GREEN,
                )
            await self._emit_tool_result(session, tool_call.name, tool_result)
            session.add_message(Message.tool(tool_result.content, tool_call.id))

            early_exit = session._consume_stop_request()
            if early_exit is not None:
                if is_debug():
                    self._log.info(
                        f"[{label}] early-exit: {early_exit.output}",
                        color=Color.CYAN,
                    )
                if stream and not emitted_text and early_exit.output:
                    yield RunEngineUpdate(chunk=early_exit.output)
                yield RunEngineUpdate(step_result=early_exit)
                return

        yield RunEngineUpdate(
            step_result=LoopStepResult(status=StepStatus.CONTINUE)
        )

    def _agent_label(self, session: AgentSession) -> str:
        agent_name = getattr(session.agent, "name", "")
        return (
            session.session_id.strip()
            or str(agent_name).strip()
            or type(session.agent).__name__
        )

    @staticmethod
    def _model_name(model: Any) -> str:
        return (
            getattr(model, "model", "")
            or getattr(model, "_model", "")
        )

    async def _emit_llm_called(
        self,
        session: AgentSession,
        model: Any,
        messages: list[dict[str, Any]],
    ) -> None:
        if session.event_bus is None:
            return

        serialized_messages = serialize_messages(messages)
        await session.event_bus.publish(
            LLMCalledEvent(
                agent_id=session.session_id,
                model=self._model_name(model),
                message_count=len(serialized_messages),
                messages=serialized_messages,
            )
        )

    async def _emit_llm_responded(
        self,
        session: AgentSession,
        model: Any,
        response: LLMResponse,
    ) -> None:
        if session.event_bus is None:
            return

        await session.event_bus.publish(
            LLMRespondedEvent(
                agent_id=session.session_id,
                model=self._model_name(model),
                content=response.content,
                tool_calls=serialize_tool_calls(response),
                usage=response.usage or {},
            )
        )

    async def _emit_llm_stream_chunk(
        self,
        session: AgentSession,
        model: Any,
        content: str,
        sequence: int,
    ) -> None:
        if session.event_bus is None:
            return
        await session.event_bus.publish(
            LLMStreamChunkEvent(
                agent_id=session.session_id,
                model=self._model_name(model),
                content=content,
                sequence=sequence,
            )
        )

    @staticmethod
    async def _emit_tool_called(
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> None:
        if session.event_bus is None:
            return
        await session.event_bus.publish(
            ToolCalledEvent(
                agent_id=session.session_id,
                tool_name=name,
                arguments=arguments,
            )
        )

    @staticmethod
    async def _emit_tool_result(
        session: AgentSession,
        name: str,
        result: ToolResult,
    ) -> None:
        if session.event_bus is None:
            return
        await session.event_bus.publish(
            ToolResultEvent(
                agent_id=session.session_id,
                tool_name=name,
                result=result.content,
                is_error=result.is_error,
                metadata=dict(result.metadata),
            )
        )


def _format_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": tool_call.id,
            "type": tool_call.type,
            "function": {
                "name": tool_call.name,
                "arguments": json.dumps(tool_call.arguments),
            },
        }
        for tool_call in tool_calls
    ]
