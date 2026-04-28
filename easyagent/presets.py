"""High-level presets — one-liner multi-agent patterns.

Each preset builds a (World, Schedule, Runtime) triple internally so
the caller only writes::

    result = await sequential([entity_a, entity_b], "prompt")
    result = await debate([alice, bob], judge=judge, seed="topic")

For manual routing, ``chatroom`` returns a ``ManualSession`` context
manager with attribute-based member invocation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyagent.core.runtime import Runtime
from easyagent.core.schedule import (
    AllParallel,
    MaxTicks,
    Reactive,
    RoundRobin,
    TakeTurns,
    UntilIdle,
)
from easyagent.core.types import RuntimeResult, Speak
from easyagent.worlds.conversation import ConversationWorld
from easyagent.worlds.pipeline import PipelineWorld

if TYPE_CHECKING:
    from easyagent.core.entity import Entity
    from easyagent.events.bus import EventBus

__all__ = [
    "sequential",
    "fanout",
    "debate",
    "chatroom",
    "groupchat",
    "ManualSession",
]


async def sequential(
    entities: list[Entity],
    seed: str,
    *,
    sender: str = "user",
    bus: EventBus | None = None,
) -> RuntimeResult:
    """Run entities in fixed order. Each sees the seed + previous outputs."""
    ids = [e.id for e in entities]
    world = PipelineWorld(order=ids)
    schedule = TakeTurns(order=ids)
    entities_map = {e.id: e for e in entities}
    rt = Runtime(world=world, entities=entities_map, schedule=schedule, bus=bus)
    return await rt.run(seed, sender=sender)


async def fanout(
    entities: list[Entity],
    seed: str,
    *,
    sender: str = "user",
    bus: EventBus | None = None,
) -> RuntimeResult:
    """All entities act once in parallel on the same seed."""
    ids = [e.id for e in entities]
    world = ConversationWorld()
    schedule = MaxTicks(inner=AllParallel(ids=ids), n=1)
    entities_map = {e.id: e for e in entities}
    rt = Runtime(world=world, entities=entities_map, schedule=schedule, bus=bus)
    return await rt.run(seed, sender=sender)


async def debate(
    entities: list[Entity],
    *,
    seed: str,
    max_rounds: int = 4,
    judge: Entity | None = None,
    sender: str = "user",
    bus: EventBus | None = None,
) -> RuntimeResult:
    """Round-robin debate. If ``judge`` is given, its verdict is appended
    as the final action after the debate loop ends."""
    ids = [e.id for e in entities]
    world = ConversationWorld()
    schedule = MaxTicks(inner=RoundRobin(ids=ids), n=max_rounds * len(ids))
    entities_map = {e.id: e for e in entities}
    rt = Runtime(world=world, entities=entities_map, schedule=schedule, bus=bus)
    result = await rt.run(seed, sender=sender)

    if judge is not None:
        from easyagent.core.types import MessagesSlice, Perception

        perception = Perception(
            entity_id=judge.id,
            tick=result.ticks,
            slices=(MessagesSlice(messages=tuple(world.history)),),
        )
        verdict = await judge.act(perception)
        if verdict is not None:
            result.actions.append((judge.id, verdict))
            if isinstance(verdict, Speak):
                world.apply(judge.id, verdict)

    return result


async def groupchat(
    entities: list[Entity],
    *,
    seed: str,
    max_rounds: int = 10,
    sender: str = "user",
    bus: EventBus | None = None,
) -> RuntimeResult:
    """Reactive turn-taking: addressed entity speaks next.
    Stops after ``max_rounds`` or when all fall silent."""
    ids = [e.id for e in entities]
    world = ConversationWorld()
    schedule = MaxTicks(
        inner=UntilIdle(inner=Reactive(ids=ids), grace=1),
        n=max_rounds,
    )
    entities_map = {e.id: e for e in entities}
    rt = Runtime(world=world, entities=entities_map, schedule=schedule, bus=bus)
    return await rt.run(seed, sender=sender)


# ── Manual session for chatroom ────────────────────────────────────────


class _MemberProxy:
    """Returned by ``ManualSession.__getattr__``. Calling it invokes the
    member entity and broadcasts the result."""

    def __init__(self, session: ManualSession, entity_id: str) -> None:
        self._session = session
        self._entity_id = entity_id

    async def __call__(self) -> str | None:
        return await self._session._invoke(self._entity_id)


class ManualSession:
    """Context manager for manual (chatroom-style) multi-agent routing.

    Usage::

        async with chatroom([drafter, critic, fixer]) as room:
            await room.drafter()
            verdict = await room.critic()
            if verdict and "approved" in verdict:
                await room.fixer()
    """

    def __init__(
        self,
        entities: dict[str, Entity],
        world: ConversationWorld,
        *,
        bus: EventBus | None = None,
    ) -> None:
        self._entities = entities
        self._world = world
        self._bus = bus
        self._tick = 0

    def __getattr__(self, name: str) -> _MemberProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._entities:
            raise AttributeError(
                f"No member named '{name}'. Available: {list(self._entities.keys())}"
            )
        return _MemberProxy(self, name)

    async def _invoke(self, entity_id: str) -> str | None:
        entity = self._entities[entity_id]
        perception = self._world.observe(entity_id)
        action = await entity.act(perception)

        if action is not None and isinstance(action, Speak):
            self._world.apply(entity_id, action)
            if self._bus is not None:
                from easyagent.events.types import MessageEvent

                await self._bus.publish(
                    MessageEvent(
                        sender=entity_id, to=action.to, content=action.content
                    )
                )
            self._tick += 1
            return action.content
        self._tick += 1
        return None

    async def __aenter__(self) -> ManualSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass


def chatroom(
    entities: list[Entity],
    *,
    announcement: str | None = None,
    bus: EventBus | None = None,
) -> ManualSession:
    """Create a manual-routing session. Use ``async with`` to enter."""
    world = ConversationWorld()
    if announcement:
        world.seed(announcement, sender="system")
    entities_map = {e.id: e for e in entities}
    return ManualSession(entities_map, world, bus=bus)
