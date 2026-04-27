"""Linear pipeline runtime: each agent does its own ReAct loop, then explicitly
"hands off" to the next agent via an injected ``end`` tool.

    runtime = PipelineRuntime([researcher, writer])
    result = await runtime.run("write a blurb about the moon")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyagent.events.bus import EventBus
from easyagent.events.types import (
    AgentFinishedEvent,
    AgentStartedEvent,
    MessageEvent,
    RuntimeFinishedEvent,
    RuntimeStartedEvent,
)
from easyagent.debug.log import Color, Logger
from easyagent.runtime.base import BaseRuntime, RuntimeResult
from easyagent.tool.end import EndTool

if TYPE_CHECKING:
    from easyagent.agent.base import BaseAgent


_log = Logger("Pipeline")


class PipelineRuntime(BaseRuntime):
    """Run a fixed list of agents in order, with explicit ``end``-tool handoffs.

    Pass freshly-constructed ReactAgent instances — PipelineRuntime replaces the
    non-terminal agents' ``end`` tool with a pipeline-aware variant.
    """

    def __init__(
        self,
        agents: list["BaseAgent"],
        *,
        bus: EventBus | None = None,
    ):
        if not agents:
            raise ValueError("PipelineRuntime needs at least one agent")

        as_dict: dict[str, "BaseAgent"] = {}
        chain: list[str] = []
        seen: dict[str, int] = {}
        for i, agent in enumerate(agents):
            base_name = getattr(agent, "name", "") or f"step_{i}"
            sid = base_name
            if sid in as_dict:
                seen[base_name] = seen.get(base_name, 1) + 1
                sid = f"{base_name}_{seen[base_name]}"
            as_dict[sid] = agent
            chain.append(sid)

        for i, sid in enumerate(chain[:-1]):
            agent = as_dict[sid]
            next_sid = chain[i + 1]
            self._swap_end_tool(agent, next_sid)

        super().__init__(as_dict, bus=bus)
        self._chain = chain

    @staticmethod
    def _swap_end_tool(agent: "BaseAgent", next_session_id: str) -> None:
        manager = getattr(agent, "_tool_manager", None)
        if manager is None:
            raise TypeError(
                f"PipelineRuntime requires a ReactAgent (got {type(agent).__name__}). "
                f"ReactAgent, SkillAgent, and SandboxAgent all qualify."
            )
        manager.register(EndTool(next_session_id=next_session_id))

    @property
    def chain(self) -> list[str]:
        return list(self._chain)

    async def run(self, user_input: str = "") -> RuntimeResult:
        await self._bus.publish(RuntimeStartedEvent(agent_ids=list(self._chain)))
        await self._enter_all_sessions()
        chain_str = " -> ".join(self._chain)
        _log.info(f"━━━ pipeline: {chain_str} ━━━", color=Color.MAGENTA)
        try:
            current: str = user_input

            seed = MessageEvent(sender="user", to="*", content=user_input)
            self._state.events.append(seed)
            await self._bus.publish(seed)

            for i, sid in enumerate(self._chain, start=1):
                session = self.sessions[sid]
                _log.info(f"━━━ step {i}/{len(self._chain)}: {sid} ━━━", color=Color.MAGENTA)
                await self._bus.publish(AgentStartedEvent(agent_id=sid))
                try:
                    current = await session.invoke(current)
                except Exception as exc:
                    await self._bus.publish(
                        AgentFinishedEvent(agent_id=sid, output=f"ERROR: {exc!r}")
                    )
                    self._state.stop_reason = f"step '{sid}' raised: {exc!r}"
                    raise
                await self._bus.publish(AgentFinishedEvent(agent_id=sid, output=current))

                step_event = MessageEvent(sender=sid, to="*", content=current)
                self._state.events.append(step_event)
                await self._bus.publish(step_event)

            self._state.stop_reason = "pipeline_complete"
        finally:
            await self._exit_all_sessions()
            await self._bus.publish(RuntimeFinishedEvent(reason=self._state.stop_reason))

        messages = [e for e in self._state.events if isinstance(e, MessageEvent)]
        return RuntimeResult(state=self._state, messages=messages)
