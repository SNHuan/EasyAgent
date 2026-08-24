"""Core perceive-act-apply runtime loop.

The Runtime is the only moving part: it wires an immutable triple of
(World, dict[str, Entity], Schedule) and drives the loop until the
Schedule returns None.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from easyagent.core.types import Composite, LoopState, RuntimeResult, Silent, Speak
from easyagent.events import (
    EntityFinishedEvent,
    EntityStartedEvent,
    MessageEvent,
    RuntimeFinishedEvent,
    RuntimeStartedEvent,
    RuntimeTickFinishedEvent,
    RuntimeTickStartedEvent,
)

if TYPE_CHECKING:
    from easyagent.core.entity import Entity
    from easyagent.core.schedule import Schedule
    from easyagent.core.types import Action
    from easyagent.core.world import World
    from easyagent.events.bus import EventBus

from easyagent.core.entity import RuntimeBindable
from easyagent.core.world import AdvancingWorld, TickAwareWorld, TraceableWorld

__all__ = ["Runtime"]


class Runtime:
    """Perceive → act → apply loop."""

    def __init__(
        self,
        *,
        world: World,
        entities: dict[str, Entity],
        schedule: Schedule,
        bus: EventBus | None = None,
        runtime_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        for entity_id, entity in entities.items():
            if entity_id != entity.id:
                raise ValueError(
                    f"entity mapping key '{entity_id}' does not match "
                    f"entity.id '{entity.id}'"
                )
        self.world = world
        self.entities = entities
        self.schedule = schedule
        self.bus = bus
        self.runtime_id = runtime_id
        self.title = title
        self.metadata = dict(metadata or {})

    async def run(
        self,
        seed: str | None = None,
        *,
        sender: str = "user",
    ) -> RuntimeResult:
        run_id = self.runtime_id or f"runtime_{uuid.uuid4().hex}"
        run_title = self.title or self.__class__.__name__
        world_summary = self._world_summary()
        entity_summaries = self._entity_summaries()

        if seed is not None:
            self.world.seed(seed, sender=sender)

        state = LoopState()
        state.metadata.update({
            "run_id": run_id,
            "run_title": run_title,
            "world": world_summary,
            "entities": entity_summaries,
        })

        await self._emit(
            RuntimeStartedEvent(
                run_id=run_id,
                run_title=run_title,
                agent_ids=list(self.entities.keys()),
                world=world_summary,
                entities=entity_summaries,
                metadata=dict(self.metadata),
            )
        )

        try:
            while True:
                active = self.schedule.next(state)
                if active is None:
                    break

                self._sync_world_clock(state.tick)
                await self._emit(
                    RuntimeTickStartedEvent(
                        run_id=run_id,
                        tick=state.tick,
                        active_entities=list(active),
                    )
                )

                tick_start = len(state.action_log)
                await self._run_tick(
                    active,
                    state,
                    run_id=run_id,
                    run_title=run_title,
                    world_summary=world_summary,
                )
                self._evolve_world(state.tick)

                state.tick_boundaries.append(len(state.action_log))
                await self._emit(
                    RuntimeTickFinishedEvent(
                        run_id=run_id,
                        tick=state.tick,
                        action_count=len(state.action_log) - tick_start,
                    )
                )
                state.tick += 1
        except Exception:
            await self._emit(
                RuntimeFinishedEvent(
                    run_id=run_id,
                    reason="error",
                    status="failed",
                    ticks=state.tick,
                    metadata=dict(self.metadata),
                )
            )
            raise

        await self._emit(
            RuntimeFinishedEvent(
                run_id=run_id,
                reason="schedule_stopped",
                status="completed",
                ticks=state.tick,
                metadata=dict(self.metadata),
            )
        )

        return RuntimeResult(
            actions=list(state.action_log),
            final_state=state,
            ticks=state.tick,
        )

    async def _run_tick(
        self,
        active: list[str],
        state: LoopState,
        *,
        run_id: str,
        run_title: str,
        world_summary: dict[str, object],
    ) -> None:
        """Run one tick: snapshot perceptions, act concurrently, apply in order.

        Every active entity observes the *same* pre-tick world snapshot, so a
        multi-entity tick is genuinely simultaneous — no entity sees another
        entity's action from the same tick. Actions are then applied in
        ``active`` order, keeping the action log deterministic regardless of
        which ``act`` coroutine finishes first.
        """
        unknown = [entity_id for entity_id in active if entity_id not in self.entities]
        if unknown:
            raise ValueError(
                f"Schedule returned unknown entity IDs: {', '.join(unknown)}"
            )
        seen: set[str] = set()
        duplicates: list[str] = []
        for entity_id in active:
            if entity_id in seen and entity_id not in duplicates:
                duplicates.append(entity_id)
            seen.add(entity_id)
        if duplicates:
            raise ValueError(
                "Schedule returned duplicate entity IDs in one tick: "
                f"{', '.join(duplicates)}"
            )
        order = list(active)
        if not order:
            return

        # ── observe phase: one immutable snapshot for the whole tick ──────
        perceptions = {}
        for entity_id in order:
            self._bind_entity_trace_context(
                entity_id=entity_id,
                entity=self.entities[entity_id],
                run_id=run_id,
                run_title=run_title,
                world=world_summary,
            )
            perceptions[entity_id] = self.world.observe(entity_id)
            await self._emit(
                EntityStartedEvent(run_id=run_id, entity_id=entity_id, tick=state.tick)
            )

        # ── act phase: concurrent for multi-entity ticks ─────────────────
        if len(order) == 1:
            entity_id = order[0]
            actions = [await self.entities[entity_id].act(perceptions[entity_id])]
        else:
            actions = await asyncio.gather(
                *(self.entities[eid].act(perceptions[eid]) for eid in order)
            )

        # ── apply phase: deterministic order ─────────────────────────────
        for entity_id, action in zip(order, actions):
            if action is not None:
                self._apply_action(entity_id, action)
                state.action_log.append((entity_id, action))
            else:
                state.action_log.append((entity_id, Silent()))

            await self._emit(
                EntityFinishedEvent(
                    run_id=run_id,
                    entity_id=entity_id,
                    tick=state.tick,
                    action_type=type(action).__name__ if action is not None else "Silent",
                )
            )
            await self._publish(entity_id, action, run_id=run_id)

    def _apply_action(self, entity_id: str, action: Action) -> None:
        if isinstance(action, Composite):
            for sub in action.actions:
                self.world.apply(entity_id, sub)
        else:
            self.world.apply(entity_id, action)

    async def _emit(self, event: object) -> None:
        """Publish an event when a bus is attached; a no-op otherwise."""
        if self.bus is not None:
            await self.bus.publish(event)

    def _sync_world_clock(self, tick: int) -> None:
        """Push the runtime tick down to the world (if it tracks one)."""
        if isinstance(self.world, TickAwareWorld):
            self.world.set_tick(tick)

    def _evolve_world(self, tick: int) -> None:
        """Let the world apply its own per-tick dynamics, if it defines any."""
        if isinstance(self.world, AdvancingWorld):
            self.world.advance(tick)

    async def _publish(self, entity_id: str, action: Action | None, *, run_id: str) -> None:
        if self.bus is None or not isinstance(action, Speak):
            return
        await self.bus.publish(
            MessageEvent(
                sender=entity_id,
                to=action.to,
                content=action.content,
                metadata={"run_id": run_id},
            )
        )

    def _bind_entity_trace_context(
        self,
        *,
        entity_id: str,
        entity: Entity,
        run_id: str,
        run_title: str,
        world: dict[str, object],
    ) -> None:
        if not isinstance(entity, RuntimeBindable):
            return
        entity.bind_runtime_context(
            run_id=run_id,
            run_title=run_title,
            world=world,
            entity=self._entity_summary(entity_id, entity),
            bus=self.bus,
        )

    def _world_summary(self) -> dict[str, object]:
        if isinstance(self.world, TraceableWorld):
            summary = self.world.trace_summary()
            if not isinstance(summary, dict):
                raise TypeError("World.trace_summary() must return dict[str, object]")
            return summary
        return {
            "world_id": getattr(self.world, "id", self.world.__class__.__name__),
            "label": getattr(self.world, "name", self.world.__class__.__name__),
            "kind": self.world.__class__.__name__,
            "status": "running",
        }

    def _entity_summaries(self) -> list[dict[str, object]]:
        return [self._entity_summary(entity_id, entity) for entity_id, entity in self.entities.items()]

    def _entity_summary(self, entity_id: str, entity: Entity) -> dict[str, object]:
        return {
            "entity_id": entity_id,
            "label": getattr(entity, "name", getattr(entity, "id", entity_id)),
            "kind": entity.__class__.__name__,
        }
