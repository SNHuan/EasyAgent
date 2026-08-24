from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any, AsyncIterator

from easyagent.agent.agent import Agent
from easyagent.agent.run_engine import ReactRunEngine
from easyagent.agent.session import AgentSession, LoopStepResult
from easyagent.checkpoint.compatibility import (
    CheckpointCompatibilityIssue,
    CheckpointCompatibilityReport,
)
from easyagent.checkpoint.schema import AgentCheckpoint
from easyagent.config.base import is_debug
from easyagent.hooks import AfterToolCallHook, BeforeToolCallHook
from easyagent.model.schema import Message, content_to_text
from easyagent.prompt.react import REACT_SYSTEM_PROMPT, build_skills_section
from easyagent.sandbox import BaseSandbox, create_sandbox
from easyagent.skill import DEFAULT_SKILL_MANAGER, SkillManager
from easyagent.tool import ToolContext, ToolManager, ToolResult
from easyagent.tool.code.bash import Bash
from easyagent.tool.code.file import ReadFile, WriteFile
from easyagent.tool.skill import (
    ListSkillFilesTool,
    LoadSkillTool,
    ReadSkillFileTool,
    RunSkillScriptTool,
)

ToolHookKey = tuple[int, int, str]
_active_tool_hook_calls: ContextVar[frozenset[ToolHookKey]] = ContextVar(
    "easyagent_active_tool_hook_calls",
    default=frozenset(),
)


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
        skills: list[str] | None = None,
        skill_root: str | Path | None = None,
        skill_manager: SkillManager | None = None,
        sandbox: BaseSandbox | dict[str, Any] | Callable[[], BaseSandbox] | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, max_steps=max_iterations, **kwargs)
        self._tool_manager = tool_manager or ToolManager(discover_builtin=False)
        self._enabled_tool_names: list[str] = []
        self._skill_manager = skill_manager or DEFAULT_SKILL_MANAGER
        self._skill_names = list(skills or [])
        self._sandbox_factory: Callable[[], BaseSandbox] | None = None
        self._shared_sandbox: BaseSandbox | None = None
        self._shared_sandbox_lock = asyncio.Lock()
        if sandbox is not None:
            self._sandbox_factory, self._shared_sandbox = self._build_sandbox_provider(
                sandbox
            )

        for t in tools or []:
            self.add_tool(t)
        if skill_root is not None:
            self._skill_manager.add_search_dir(Path(skill_root))
        if self._skill_names:
            self.add_tool(LoadSkillTool(self._skill_manager, self._skill_names))
            self.add_tool(ListSkillFilesTool(self._skill_manager))
            self.add_tool(ReadSkillFileTool(self._skill_manager))
            self.add_tool(RunSkillScriptTool(self._skill_manager))
        if self._sandbox_factory is not None or self._shared_sandbox is not None:
            self.add_tool([Bash(), WriteFile(), ReadFile()])
        self._run_engine = ReactRunEngine(
            get_model=lambda: self.default_model,
            get_tool_schemas=lambda session: self.get_tool_schemas(session),
            execute_tool_call=self._execute_tool_call_for_engine,
            max_steps=self._max_steps,
            logger=self._log,
        )

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

    def check_checkpoint(
        self,
        checkpoint: AgentCheckpoint,
    ) -> CheckpointCompatibilityReport:
        report = super().check_checkpoint(checkpoint)
        issues = list(report.issues)
        registered_tools = self._tool_manager.registered_names()
        missing_tools = sorted(
            {
                name
                for name in checkpoint.enabled_tools
                if name not in registered_tools
            }
        )
        if missing_tools:
            issues.append(
                CheckpointCompatibilityIssue(
                    code="missing_tools",
                    message=f"Missing tools: {', '.join(missing_tools)}",
                    missing=tuple(missing_tools),
                )
            )
        missing_skills = sorted(
            {
                name
                for name in checkpoint.loaded_skills
                if name not in self._skill_names
            }
        )
        if missing_skills:
            issues.append(
                CheckpointCompatibilityIssue(
                    code="missing_skills",
                    message=f"Missing skills: {', '.join(missing_skills)}",
                    missing=tuple(missing_skills),
                )
            )
        return CheckpointCompatibilityReport(issues=tuple(issues))

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def on_session_start(self, session: AgentSession) -> None:
        await super().on_session_start(session)
        sandbox: BaseSandbox | None = None
        shared_lock_acquired = False
        if self._shared_sandbox is not None:
            await self._shared_sandbox_lock.acquire()
            shared_lock_acquired = True
            sandbox = self._shared_sandbox
        elif self._sandbox_factory is not None:
            sandbox = self._sandbox_factory()

        if sandbox is None:
            return
        if not isinstance(sandbox, BaseSandbox):
            if shared_lock_acquired:
                self._shared_sandbox_lock.release()
            raise TypeError("sandbox factory must return a BaseSandbox")

        session.sandbox = sandbox
        session.resources["_easyagent_sandbox_owned"] = True
        session.resources["_easyagent_shared_sandbox_lock"] = shared_lock_acquired
        try:
            await sandbox.start()
        except BaseException:
            session.sandbox = None
            session.resources.pop("_easyagent_sandbox_owned", None)
            session.resources.pop("_easyagent_shared_sandbox_lock", None)
            if shared_lock_acquired:
                self._shared_sandbox_lock.release()
            raise

    async def on_session_end(self, session: AgentSession) -> None:
        owns_sandbox = bool(
            session.resources.pop("_easyagent_sandbox_owned", False)
        )
        shared_lock_acquired = bool(
            session.resources.pop("_easyagent_shared_sandbox_lock", False)
        )
        sandbox = session.sandbox if owns_sandbox else None
        if sandbox is not None:
            try:
                await sandbox.stop()
            finally:
                session.sandbox = None
                if shared_lock_acquired:
                    self._shared_sandbox_lock.release()
        await super().on_session_end(session)

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

        if isinstance(user_input, Message):
            session.add_message(user_input)
        else:
            session.add_message(Message.user(user_input))
        session.iteration_count = 0
        session.loop_steps.clear()
        session.loop_state.clear()

        while True:
            result: LoopStepResult | None = None
            async for update in self._run_engine.execute_step(
                session,
                self.build_system_prompt(session),
                stream=True,
            ):
                if update.chunk is not None:
                    yield update.chunk
                else:
                    result = update.step_result
            if result is None:
                raise RuntimeError("Run engine completed without a step result")
            await session._record_step(result)
            if result.done:
                break

        if result.output:
            session.final_output = result.output

    # ── ReAct step ───────────────────────────────────────────────────────

    async def step(
        self,
        session: AgentSession,
    ) -> LoopStepResult:
        result: LoopStepResult | None = None
        async for update in self._run_engine.execute_step(
            session,
            self.build_system_prompt(session),
            stream=False,
        ):
            if update.chunk is not None:
                raise RuntimeError(
                    "Non-streaming run engine emitted a text chunk"
                )
            result = update.step_result
        if result is None:
            raise RuntimeError("Run engine completed without a step result")
        return result

    # ── extension points ─────────────────────────────────────────────────

    def build_system_prompt(self, session: AgentSession) -> str:
        base = super().build_system_prompt(session)
        sections = [REACT_SYSTEM_PROMPT]
        if base:
            sections.append(base)
        skill_section = build_skills_section(
            self._skill_manager.list_summaries(self._skill_names)
        )
        if skill_section:
            sections.append(skill_section)
        return "\n\n".join(sections)

    def get_tool_schemas(self, session: AgentSession) -> list[dict[str, Any]]:
        return self._tool_manager.get_schema(session.enabled_tools)

    async def execute_tool_call(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        hook_key = (id(self), id(session), name)
        if hook_key in _active_tool_hook_calls.get():
            result = await self._execute_registered_tool_call(
                session,
                name,
                arguments,
            )
        else:
            result = await self._execute_tool_call_result(
                session,
                name,
                arguments,
            )
        return result.content

    async def _execute_tool_call_result(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        return await self._execute_tool_call_with_hooks(
            session,
            name,
            arguments,
            self._execute_registered_tool_call,
        )

    async def _execute_tool_call_for_engine(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        executor = self.execute_tool_call
        if getattr(executor, "__func__", None) is ReactAgent.execute_tool_call:
            return await self._execute_tool_call_result(session, name, arguments)
        return await self._execute_tool_call_with_hooks(
            session,
            name,
            arguments,
            executor,
        )

    async def _execute_tool_call_with_hooks(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
        executor: Callable[
            [AgentSession, str, dict[str, Any]],
            Awaitable[str | ToolResult],
        ],
    ) -> ToolResult:
        before = await self.hooks.emit(
            BeforeToolCallHook(
                session=session,
                tool_name=name,
                arguments=dict(arguments),
            )
        )
        if before.blocked:
            result = ToolResult(
                content=before.reason or f"Tool '{name}' was blocked by a hook",
                is_error=True,
                metadata={"blocked": True},
            )
        else:
            hook_key = (id(self), id(session), name)
            active_calls = _active_tool_hook_calls.get()
            token = _active_tool_hook_calls.set(
                active_calls | {hook_key}
            )
            try:
                value = await executor(
                    session,
                    name,
                    before.arguments,
                )
            finally:
                _active_tool_hook_calls.reset(token)
            result = (
                value
                if isinstance(value, ToolResult)
                else ToolResult(content="" if value is None else str(value))
            )
        after = await self.hooks.emit(
            AfterToolCallHook(
                session=session,
                tool_name=name,
                arguments=before.arguments,
                result=result,
            )
        )
        return after.result

    async def _execute_registered_tool_call(
        self,
        session: AgentSession,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        if name not in session.enabled_tools:
            return ToolResult(
                content=f"Tool '{name}' is not enabled",
                is_error=True,
            )
        if self._tool_manager.get(name) is None:
            return ToolResult(
                content=f"Tool '{name}' not found",
                is_error=True,
            )
        return await self._tool_manager.execute(
            name,
            arguments,
            ToolContext(session=session),
        )

    # ── internals ────────────────────────────────────────────────────────

    def _agent_label(self, session: AgentSession) -> str:
        return session.session_id.strip() or self.name.strip() or self.__class__.__name__

    @staticmethod
    def _build_sandbox_provider(
        sandbox: BaseSandbox | dict[str, Any] | Callable[[], BaseSandbox],
    ) -> tuple[Callable[[], BaseSandbox] | None, BaseSandbox | None]:
        if isinstance(sandbox, dict):
            config = sandbox.copy()
            sandbox_type = config.pop("type", "local")
            return (
                lambda: create_sandbox(sandbox_type=sandbox_type, **config),
                None,
            )
        if isinstance(sandbox, BaseSandbox):
            return None, sandbox
        if callable(sandbox):
            return sandbox, None
        raise TypeError("sandbox must be a BaseSandbox, config dict, or factory")
