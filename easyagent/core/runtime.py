"""Core perceive-act-apply runtime loop.

The Runtime is the only moving part: it wires an immutable triple of
(World, dict[str, Entity], Schedule) and drives the loop until the
Schedule returns None.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from easyagent.core.types import Composite, LoopState, RuntimeResult, Silent

if TYPE_CHECKING:
    from easyagent.core.entity import Entity
    from easyagent.core.schedule import Schedule
    from easyagent.core.types import Action
    from easyagent.core.world import World
    from easyagent.events.bus import EventBus

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

        if self.bus is not None:
            from easyagent.events import RuntimeStartedEvent

            await self.bus.publish(
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

                if self.bus is not None:
                    from easyagent.events import RuntimeTickStartedEvent

                    await self.bus.publish(
                        RuntimeTickStartedEvent(
                            run_id=run_id,
                            tick=state.tick,
                            active_entities=list(active),
                        )
                    )

                tick_start = len(state.action_log)
                for entity_id in active:
                    if entity_id not in self.entities:
                        continue
                    entity = self.entities[entity_id]
                    self._bind_entity_trace_context(
                        entity_id=entity_id,
                        entity=entity,
                        run_id=run_id,
                        run_title=run_title,
                        world=world_summary,
                    )
                    perception = self.world.observe(entity_id)
                    if self.bus is not None:
                        from easyagent.events import EntityStartedEvent

                        await self.bus.publish(
                            EntityStartedEvent(run_id=run_id, entity_id=entity_id, tick=state.tick)
                        )
                    action = await entity.act(perception)

                    if action is not None:
                        self._apply_action(entity_id, action)
                        state.action_log.append((entity_id, action))
                    else:
                        state.action_log.append((entity_id, Silent()))

                    if self.bus is not None:
                        from easyagent.events import EntityFinishedEvent

                        await self.bus.publish(
                            EntityFinishedEvent(
                                run_id=run_id,
                                entity_id=entity_id,
                                tick=state.tick,
                                action_type=type(action).__name__ if action is not None else "Silent",
                            )
                        )
                        await self._publish(entity_id, action, run_id=run_id)

                state.tick_boundaries.append(len(state.action_log))
                if self.bus is not None:
                    from easyagent.events import RuntimeTickFinishedEvent

                    await self.bus.publish(
                        RuntimeTickFinishedEvent(
                            run_id=run_id,
                            tick=state.tick,
                            action_count=len(state.action_log) - tick_start,
                        )
                    )
                state.tick += 1
        except Exception:
            if self.bus is not None:
                from easyagent.events import RuntimeFinishedEvent

                await self.bus.publish(
                    RuntimeFinishedEvent(
                        run_id=run_id,
                        reason="error",
                        status="failed",
                        ticks=state.tick,
                        metadata=dict(self.metadata),
                    )
                )
            raise

        if self.bus is not None:
            from easyagent.events import RuntimeFinishedEvent

            await self.bus.publish(
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

    def _apply_action(self, entity_id: str, action: Action) -> None:
        if isinstance(action, Composite):
            for sub in action.actions:
                self.world.apply(entity_id, sub)
        else:
            self.world.apply(entity_id, action)

    async def _publish(self, entity_id: str, action: Action | None, *, run_id: str) -> None:
        from easyagent.events.types import MessageEvent
        from easyagent.core.types import Speak

        if action is None or not isinstance(action, Speak):
            return
        assert self.bus is not None
        to = action.to if isinstance(action.to, str) else action.to
        await self.bus.publish(
            MessageEvent(sender=entity_id, to=to, content=action.content, metadata={"run_id": run_id})
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
        binder = getattr(entity, "bind_runtime_context", None)
        if not callable(binder):
            return
        binder(
            run_id=run_id,
            run_title=run_title,
            world=world,
            entity=self._entity_summary(entity_id, entity),
            bus=self.bus,
        )

    def _world_summary(self) -> dict[str, object]:
        trace_summary = getattr(self.world, "trace_summary", None)
        if callable(trace_summary):
            value = trace_summary()
            if isinstance(value, dict):
                return value
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
