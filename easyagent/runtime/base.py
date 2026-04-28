from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from easyagent.debug.log import Color, Logger
from easyagent.events.base import BaseEvent
from easyagent.events.bus import EventBus
from easyagent.events.types import (
    AgentFinishedEvent,
    AgentId,
    AgentStartedEvent,
    MessageEvent,
    RuntimeFinishedEvent,
    RuntimeStartedEvent,
    WaitEvent,
)
from easyagent.runtime.policies import (
    Delivery,
    Parallel,
    SchedulePolicy,
    Sequential,
    Shuffled,
    StepPolicy,
    StopPolicy,
)
from easyagent.runtime.state import RuntimeState

if TYPE_CHECKING:
    from easyagent.agent.base import BaseAgent
    from easyagent.agent.session import AgentSession


_log = Logger("Runtime")


@dataclass
class RuntimeResult:
    state: RuntimeState
    messages: list[MessageEvent] = field(default_factory=list)

    @property
    def stop_reason(self) -> str:
        return self.state.stop_reason


# ── BaseRuntime: pure abstraction ────────────────────────────────────────


class BaseRuntime(ABC):
    """A group of agents sharing an EventBus.

    This is the minimal contract. It holds sessions, a bus, and runtime state.
    HOW the agents are orchestrated (tick loop, event-driven, continuous) is
    up to subclasses.

    The dispatch key is the **session id**. The common case is one session per
    agent:

      Runtime(agents={"alice": alice_agent, "bob": bob_agent}, ...)

    If you need multiple workers, pass multiple agents or call ``add_agent``
    repeatedly with distinct names.
    """

    def __init__(
        self,
        agents: dict[AgentId, "BaseAgent"] | None = None,
        *,
        bus: EventBus | None = None,
        name: str = "runtime",
    ):
        self._bus = bus or EventBus()
        self.sessions: dict[AgentId, "AgentSession"] = {}
        self._log = _log
        self._state = RuntimeState(agent_ids=[])
        self._name = name

        for agent_name, agent in (agents or {}).items():
            self.add_agent(agent_name, agent)

    @property
    def name(self) -> str:
        """Stable container name. Used by ``RuntimeTalker`` so callers
        of a runtime-as-Talker see this name as the sender of the
        runtime's outbound message rather than the name of whichever
        internal agent happened to speak last.
        """
        return self._name

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def state(self) -> RuntimeState:
        return self._state

    # ── Session management ────────────────────────────────────────────────

    def add_agent(self, name: str, agent: "BaseAgent") -> "AgentSession":
        """Create one session for ``agent`` and add it to the runtime."""
        if name in self.sessions:
            raise ValueError(f"Agent '{name}' is already in this runtime")
        session = agent.create_session()
        session.session_id = name
        session.agent = agent
        session.event_bus = self._bus
        self.sessions[name] = session
        self._install_stop_listener(session)
        self._state.agent_ids = list(self.sessions.keys())
        return session

    def _install_stop_listener(self, session: "AgentSession") -> None:
        """Wire ``StopEvent`` for this session into ``loop_state['__early_exit__']``.

        StopEvent is the public, observable signal "please terminate session
        ``sid``'s in-flight loop". The actual loop (e.g. ReActLoop) does NOT
        subscribe to the bus directly — it only checks
        ``session.loop_state['__early_exit__']`` after each tool call. This
        listener bridges the two: if a StopEvent matches our session id, copy
        its ``data`` into the loop_state slot so the loop breaks out cleanly
        on its next checkpoint.
        """
        from easyagent.events.types import StopEvent

        target_sid = session.session_id

        def _on_stop(event: StopEvent) -> None:
            if event.session_id != target_sid:
                return
            session.loop_state["__early_exit__"] = event.data

        self._bus.subscribe(StopEvent, _on_stop)

    def send(self, event: BaseEvent) -> None:
        """Stage a seed event for the next ``run()``.

        For now this is a thin convenience: events are appended to a pending
        queue and consumed by the next call to ``run()`` as if passed via
        ``run(seed_events=...)``. Subclasses may override for live injection.
        """
        if not hasattr(self, "_pending_seed_events"):
            self._pending_seed_events: list[BaseEvent] = []
        self._pending_seed_events.append(event)

    # ── shared helpers for subclasses ─────────────────────────────────────

    def _group_deliveries(self, deliveries: list[Delivery]) -> dict[AgentId, list[BaseEvent]]:
        grouped: dict[AgentId, list[BaseEvent]] = {}
        for agent_id, event in deliveries:
            grouped.setdefault(agent_id, []).append(event)
        return grouped

    async def _call_agent(self, agent_id: AgentId, events: list[BaseEvent]) -> list[BaseEvent]:
        agent_session = self.sessions[agent_id]
        agent_session.metadata["tick"] = self._state.tick
        agent_session.metadata["max_ticks"] = self._state.max_ticks
        await self._bus.publish(AgentStartedEvent(agent_id=agent_id))
        try:
            result = await agent_session.on_events(events)
        except Exception as exc:  # noqa: BLE001
            self._log.error(f"agent {agent_id}.step raised: {exc!r}", color=Color.RED)
            await self._bus.publish(
                AgentFinishedEvent(agent_id=agent_id, output=f"ERROR: {exc!r}")
            )
            return []
        await self._bus.publish(AgentFinishedEvent(agent_id=agent_id, output=""))
        return list(result or [])

    async def _enter_all_sessions(self) -> None:
        for session in self.sessions.values():
            if session.agent is not None:
                await session.agent.on_session_start(session)

    async def _exit_all_sessions(self) -> None:
        for session in self.sessions.values():
            if session.agent is not None:
                await session.agent.on_session_end(session)

    @abstractmethod
    async def run(self, *args, **kwargs) -> RuntimeResult:
        """Run the runtime. Subclasses define the orchestration strategy and
        their own ``run`` signature. Examples:

          - ``TickBasedRuntime.run(seed_events: list[BaseEvent] | None = None)``
        """


# ── TickBasedRuntime: tick loop + policies ───────────────────────────────


class TickBasedRuntime(BaseRuntime):
    """Runtime that orchestrates agents in discrete ticks.

    Provides the tick loop, stop/step policy integration, WaitEvent handling,
    and undeliverable message detection. Execution order within a tick is
    decided by ``schedule_policy``: see :class:`SchedulePolicy` for the
    batch-list contract. Default is ``Sequential`` (deterministic order;
    earlier agents' outputs visible to later ones in the same tick).
    """

    def __init__(
        self,
        agents: dict[AgentId, "BaseAgent"] | None = None,
        *,
        step_policy: StepPolicy,
        stop_policy: StopPolicy,
        schedule_policy: SchedulePolicy | None = None,
        bus: EventBus | None = None,
        name: str = "tick_runtime",
    ):
        super().__init__(agents, bus=bus, name=name)
        self._step_policy = step_policy
        self._stop_policy = stop_policy
        if schedule_policy is None:
            schedule_policy = Sequential()
        self._schedule_policy = schedule_policy

    @property
    def state(self) -> RuntimeState:
        return self._state

    async def on_undeliverable(self, event: MessageEvent) -> BaseEvent | None:
        """Called when a message targets agents not in this runtime.

        Override for human-in-the-loop. Return None to drop (default).
        """
        return None

    async def run(self, seed_events: list[BaseEvent] | None = None) -> RuntimeResult:
        if not self.sessions:
            raise ValueError("Runtime needs at least one agent before run()")
        # Drain any events queued via send().
        queued: list[BaseEvent] = list(getattr(self, "_pending_seed_events", []))
        if hasattr(self, "_pending_seed_events"):
            self._pending_seed_events.clear()
        all_seed = queued + list(seed_events or [])
        await self._bus.publish(RuntimeStartedEvent(agent_ids=list(self.sessions.keys())))
        await self._enter_all_sessions()
        try:
            result = await self._run_tick_loop(all_seed if all_seed else None)
        finally:
            await self._exit_all_sessions()
        return result

    async def _run_tick_loop(self, seed_events: list[BaseEvent] | None) -> RuntimeResult:
        pending: list[Delivery] = []
        if seed_events:
            self._log.info("━━━ seed ━━━", color=Color.MAGENTA)
            for event in seed_events:
                pending.extend(await self._record_and_route(event))

        while True:
            self._state.tick += 1

            stop, reason = self._stop_policy.should_stop(self._state)
            if stop:
                self._state.stop_reason = reason
                break

            tick_label = f"tick {self._state.tick}"
            if self._state.max_ticks:
                tick_label = f"tick {self._state.tick}/{self._state.max_ticks}"
            self._log.info(f"━━━ {tick_label} ━━━", color=Color.MAGENTA)

            next_pending: list[Delivery] = []

            if pending:
                new_events = await self._run_batch(pending)
                next_pending.extend(await self._handle_produced_events(new_events))

            tick_deliveries = self._deliveries_on_tick()
            if tick_deliveries:
                tick_events = await self._run_batch(tick_deliveries)
                next_pending.extend(await self._handle_produced_events(tick_events))

            if next_pending:
                self._state.idle_steps = 0
            else:
                self._state.idle_steps += 1

            pending = next_pending

        await self._bus.publish(RuntimeFinishedEvent(reason=self._state.stop_reason))
        messages = [e for e in self._state.events if isinstance(e, MessageEvent)]
        return RuntimeResult(state=self._state, messages=messages)

    def _deliveries_on_tick(self) -> list[Delivery]:
        method = getattr(self._step_policy, "deliveries_on_tick", None)
        if method is None:
            return []
        return method(self.sessions, self._state)

    async def _handle_produced_events(self, events: list[BaseEvent]) -> list[Delivery]:
        next_pending: list[Delivery] = []
        for event in events:
            if isinstance(event, WaitEvent):
                next_pending.append((event.agent_id, event))
                continue
            next_pending.extend(await self._record_and_route(event))
            reply = await self._check_undeliverable(event)
            if reply is not None:
                next_pending.extend(await self._record_and_route(reply))
        return next_pending

    async def _record_and_route(self, event: BaseEvent) -> list[Delivery]:
        self._state.events.append(event)
        await self._bus.publish(event)
        return self._step_policy.deliveries(event, self.sessions, self._state)

    async def _run_batch(self, deliveries: list[Delivery]) -> list[BaseEvent]:
        """Execute one tick's deliveries according to the schedule policy.

        Schedule policy returns a list of batches. Each batch runs concurrently
        via ``asyncio.gather``. Between batches, the events produced by earlier
        batches become visible to later batches (only ``MessageEvent``s that
        are visible to the receiving agent and not from itself).
        """
        grouped = self._group_deliveries(deliveries)
        agent_ids = list(grouped.keys())
        batches = self._schedule_policy.order(agent_ids, self._state)
        if not batches:
            return []

        order_str = " -> ".join(" + ".join(batch) for batch in batches)
        self._log.info(f"  schedule: {order_str}", color=Color.GRAY)

        all_produced: list[BaseEvent] = []
        for batch in batches:
            batch_calls = []
            for aid in batch:
                events = list(grouped.get(aid, []))
                events.extend(_visible_messages(all_produced, aid))
                batch_calls.append(self._call_agent(aid, events))
            results = await asyncio.gather(*batch_calls)
            for produced in results:
                all_produced.extend(produced)
        return all_produced

    async def _check_undeliverable(self, event: BaseEvent) -> BaseEvent | None:
        if not isinstance(event, MessageEvent):
            return None
        if event.is_broadcast:
            return None
        unknown = set(event.to) - set(self.sessions.keys())  # type: ignore[arg-type]
        if not unknown:
            return None
        return await self.on_undeliverable(event)


def _visible_messages(produced: list[BaseEvent], agent_id: AgentId) -> list[BaseEvent]:
    return [
        e for e in produced
        if isinstance(e, MessageEvent) and e.sender != agent_id and e.visible_to(agent_id)
    ]


class ParallelRuntime(TickBasedRuntime):
    """Tick runtime with all active sessions in one concurrent batch."""

    def __init__(
        self,
        agents: dict[AgentId, "BaseAgent"] | None = None,
        *,
        step_policy: StepPolicy,
        stop_policy: StopPolicy,
        bus: EventBus | None = None,
        name: str = "parallel_runtime",
    ):
        super().__init__(
            agents,
            step_policy=step_policy,
            stop_policy=stop_policy,
            schedule_policy=Parallel(),
            bus=bus,
            name=name,
        )


class SequentialRuntime(TickBasedRuntime):
    """Tick runtime with active sessions run one by one in insertion order."""

    def __init__(
        self,
        agents: dict[AgentId, "BaseAgent"] | None = None,
        *,
        step_policy: StepPolicy,
        stop_policy: StopPolicy,
        bus: EventBus | None = None,
        name: str = "sequential_runtime",
    ):
        super().__init__(
            agents,
            step_policy=step_policy,
            stop_policy=stop_policy,
            schedule_policy=Sequential(),
            bus=bus,
            name=name,
        )


class ShuffledRuntime(TickBasedRuntime):
    """Tick runtime with active sessions run one by one in random order."""

    def __init__(
        self,
        agents: dict[AgentId, "BaseAgent"] | None = None,
        *,
        step_policy: StepPolicy,
        stop_policy: StopPolicy,
        bus: EventBus | None = None,
        name: str = "shuffled_runtime",
    ):
        super().__init__(
            agents,
            step_policy=step_policy,
            stop_policy=stop_policy,
            schedule_policy=Shuffled(),
            bus=bus,
            name=name,
        )
