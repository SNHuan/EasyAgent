"""Core perceive-act-apply runtime loop.

The Runtime is the only moving part: it wires an immutable triple of
(World, dict[str, Entity], Schedule) and drives the loop until the
Schedule returns None.
"""

from __future__ import annotations

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
    ) -> None:
        self.world = world
        self.entities = entities
        self.schedule = schedule
        self.bus = bus

    async def run(
        self,
        seed: str | None = None,
        *,
        sender: str = "user",
    ) -> RuntimeResult:
        if seed is not None:
            self.world.seed(seed, sender=sender)

        state = LoopState()

        while True:
            active = self.schedule.next(state)
            if active is None:
                break

            for entity_id in active:
                if entity_id not in self.entities:
                    continue
                perception = self.world.observe(entity_id)
                action = await self.entities[entity_id].act(perception)

                if action is not None:
                    self._apply_action(entity_id, action)
                    state.action_log.append((entity_id, action))
                else:
                    state.action_log.append((entity_id, Silent()))

                if self.bus is not None:
                    await self._publish(entity_id, action)

            state.tick_boundaries.append(len(state.action_log))
            state.tick += 1

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

    async def _publish(self, entity_id: str, action: Action | None) -> None:
        from easyagent.events.types import MessageEvent
        from easyagent.core.types import Speak

        if action is None or not isinstance(action, Speak):
            return
        assert self.bus is not None
        to = action.to if isinstance(action.to, str) else action.to
        await self.bus.publish(
            MessageEvent(sender=entity_id, to=to, content=action.content)
        )
