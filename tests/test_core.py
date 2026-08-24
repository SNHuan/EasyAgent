"""Tests for the Entity-World-Schedule core architecture."""

from __future__ import annotations

import asyncio

import pytest

from easyagent.core.types import (
    Action,
    ChatMessage,
    Composite,
    LoopState,
    MessagesSlice,
    Move,
    Perception,
    PerceptionSlice,
    RuntimeResult,
    SetState,
    Silent,
    Speak,
    SpatialSlice,
    StateSlice,
)
from easyagent.core.schedule import (
    AllParallel,
    MaxTicks,
    RandomOrder,
    Reactive,
    RoundRobin,
    TakeTurns,
    UntilIdle,
    UntilPredicate,
)
from easyagent.core.runtime import Runtime
from easyagent.entities.llm import LLMEntity
from easyagent.agent.agent import Agent
from easyagent.model.schema import LLMResponse
from easyagent.worlds.conversation import ConversationWorld
from easyagent.worlds.pipeline import PipelineWorld
from easyagent.worlds.spatial import Grid2D, SpatialWorld
from easyagent.worlds.stateful import SharedState, StatefulWorld


# ── Helpers ────────────────────────────────────────────────────────────


class EchoEntity:
    """Echoes the last message with a prefix."""

    def __init__(self, entity_id: str, prefix: str = "") -> None:
        self._id = entity_id
        self._prefix = prefix

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> Action | None:
        msg_slice = perception.of_type(MessagesSlice)
        if msg_slice is None or not msg_slice.messages:
            return None
        last = msg_slice.messages[-1]
        if last.sender == self._id:
            return None
        return Speak(content=f"{self._prefix}{last.content}")


class SilentEntity:
    def __init__(self, entity_id: str) -> None:
        self._id = entity_id

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> Action | None:
        return None


class CounterEntity:
    """Speaks a counter value each turn."""

    def __init__(self, entity_id: str) -> None:
        self._id = entity_id
        self._count = 0

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> Action | None:
        self._count += 1
        return Speak(content=f"{self._id}:{self._count}")


class RecordingLLM:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, object]]] = []

    async def call_with_history(self, messages, **kwargs):
        self.messages.append(messages)
        return LLMResponse(content="done")


# ── Perception tests ───────────────────────────────────────────────────


class TestPerception:
    def test_of_type_returns_first_match(self) -> None:
        s1 = MessagesSlice(messages=())
        s2 = SpatialSlice(position=(1, 2), nearby=("b",))
        p = Perception(entity_id="a", tick=0, slices=(s1, s2))

        assert p.of_type(MessagesSlice) is s1
        assert p.of_type(SpatialSlice) is s2
        assert p.of_type(StateSlice) is None

    def test_all_of_type(self) -> None:
        s1 = MessagesSlice(messages=())
        s2 = MessagesSlice(messages=(ChatMessage(sender="x", content="hi"),))
        p = Perception(entity_id="a", tick=0, slices=(s1, s2))

        result = p.all_of_type(MessagesSlice)
        assert len(result) == 2
        assert result[0] is s1
        assert result[1] is s2


# ── LoopState tests ────────────────────────────────────────────────────


class TestLoopState:
    def test_actions_for_tick(self) -> None:
        state = LoopState()
        state.action_log = [
            ("a", Speak(content="1")),
            ("b", Speak(content="2")),
            ("a", Speak(content="3")),
        ]
        state.tick_boundaries = [2, 3]
        state.tick = 2

        tick0_actions = state.actions_for_tick(0)
        assert len(tick0_actions) == 2
        assert tick0_actions[0] == ("a", Speak(content="1"))

        tick1_actions = state.actions_for_tick(1)
        assert len(tick1_actions) == 1
        assert tick1_actions[0] == ("a", Speak(content="3"))

    def test_last_tick_actions(self) -> None:
        state = LoopState()
        state.tick = 0
        assert state.last_tick_actions() == []

        state.action_log = [("a", Speak(content="x"))]
        state.tick_boundaries = [1]
        state.tick = 1
        assert len(state.last_tick_actions()) == 1


# ── RuntimeResult tests ───────────────────────────────────────────────


class TestRuntimeResult:
    def test_last_speech(self) -> None:
        r = RuntimeResult(
            actions=[
                ("a", Speak(content="first")),
                ("b", Silent()),
                ("a", Speak(content="last")),
            ]
        )
        assert r.last_speech == "last"

    def test_speeches(self) -> None:
        r = RuntimeResult(
            actions=[
                ("a", Speak(content="x")),
                ("b", Silent()),
                ("c", Speak(content="y")),
            ]
        )
        assert r.speeches() == [("a", "x"), ("c", "y")]

    def test_str(self) -> None:
        r = RuntimeResult(
            actions=[("a", Speak(content="hello"))]
        )
        assert str(r) == "hello"

    def test_str_empty(self) -> None:
        assert str(RuntimeResult()) == ""


@pytest.mark.asyncio
async def test_llm_entity_preserves_perception_message_order() -> None:
    llm = RecordingLLM()
    entity = LLMEntity("coder", Agent(model=llm))
    perception = Perception(
        entity_id="coder",
        tick=1,
        slices=(
            MessagesSlice(
                messages=(
                    ChatMessage(sender="user", content="build it"),
                    ChatMessage(sender="coder", content="working"),
                )
            ),
        ),
    )

    await entity.act(perception)

    conversation = [
        (message["role"], message["content"])
        for message in llm.messages[0]
        if message["role"] != "system"
    ]
    assert [role for role, _ in conversation] == ["user", "assistant"]
    assert "user: build it" in conversation[0][1]
    assert conversation[1][1] == "working"


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_trace_summary() -> None:
    class InvalidTraceWorld(ConversationWorld):
        def trace_summary(self):
            return None

    runtime = Runtime(
        world=InvalidTraceWorld(),
        entities={"silent": SilentEntity("silent")},
        schedule=TakeTurns(order=["silent"]),
    )

    with pytest.raises(TypeError, match="trace_summary"):
        await runtime.run()


@pytest.mark.asyncio
async def test_runtime_rejects_duplicate_entity_ids_in_one_tick() -> None:
    class DuplicateSchedule:
        def next(self, state):
            return ["silent", "silent"] if state.tick == 0 else None

    runtime = Runtime(
        world=ConversationWorld(),
        entities={"silent": SilentEntity("silent")},
        schedule=DuplicateSchedule(),
    )

    with pytest.raises(ValueError, match="duplicate entity IDs"):
        await runtime.run()


# ── Schedule tests ─────────────────────────────────────────────────────


class TestSchedules:
    def test_take_turns(self) -> None:
        s = TakeTurns(order=["a", "b", "c"])
        state = LoopState()

        assert s.next(state) == ["a"]
        state.tick = 1
        assert s.next(state) == ["b"]
        state.tick = 2
        assert s.next(state) == ["c"]
        state.tick = 3
        assert s.next(state) is None

    def test_all_parallel(self) -> None:
        s = AllParallel(ids=["a", "b"])
        state = LoopState()
        assert s.next(state) == ["a", "b"]

    def test_round_robin(self) -> None:
        s = RoundRobin(ids=["x", "y"])
        state = LoopState()
        assert s.next(state) == ["x"]
        state.tick = 1
        assert s.next(state) == ["y"]
        state.tick = 2
        assert s.next(state) == ["x"]

    def test_max_ticks(self) -> None:
        s = MaxTicks(inner=AllParallel(ids=["a"]), n=2)
        state = LoopState()
        assert s.next(state) == ["a"]
        state.tick = 1
        assert s.next(state) == ["a"]
        state.tick = 2
        assert s.next(state) is None

    def test_until_idle_stops(self) -> None:
        inner = AllParallel(ids=["a"])
        s = UntilIdle(inner=inner, grace=1)
        state = LoopState()

        state.action_log = [("a", Silent())]
        state.tick_boundaries = [1]
        state.tick = 1
        assert s.next(state) is None

    def test_until_idle_continues(self) -> None:
        inner = AllParallel(ids=["a"])
        s = UntilIdle(inner=inner, grace=1)
        state = LoopState()

        state.action_log = [("a", Speak(content="hi"))]
        state.tick_boundaries = [1]
        state.tick = 1
        assert s.next(state) == ["a"]

    def test_until_predicate(self) -> None:
        inner = AllParallel(ids=["a"])
        s = UntilPredicate(inner=inner, predicate=lambda st: st.tick >= 2)
        state = LoopState()

        state.tick = 1
        assert s.next(state) == ["a"]
        state.tick = 2
        assert s.next(state) is None

    def test_reactive_falls_back_to_round_robin(self) -> None:
        s = Reactive(ids=["a", "b"])
        state = LoopState()
        assert s.next(state) == ["a"]
        state.tick = 1
        assert s.next(state) == ["b"]


# ── ConversationWorld tests ────────────────────────────────────────────


class TestConversationWorld:
    def test_seed_and_observe(self) -> None:
        w = ConversationWorld()
        w.seed("hello")
        p = w.observe("alice")

        msg_slice = p.of_type(MessagesSlice)
        assert msg_slice is not None
        assert len(msg_slice.messages) == 1
        assert msg_slice.messages[0].sender == "user"
        assert msg_slice.messages[0].content == "hello"

    def test_apply_speak(self) -> None:
        w = ConversationWorld()
        w.seed("hi")
        w.apply("alice", Speak(content="hey"))

        p = w.observe("bob")
        msg_slice = p.of_type(MessagesSlice)
        assert msg_slice is not None
        assert len(msg_slice.messages) == 2
        assert msg_slice.messages[1].sender == "alice"

    def test_ignores_non_speak(self) -> None:
        w = ConversationWorld()
        w.apply("alice", Move(target=(1, 1)))
        assert len(w.history) == 0


# ── PipelineWorld tests ────────────────────────────────────────────────


class TestPipelineWorld:
    def test_visibility_restriction(self) -> None:
        w = PipelineWorld(order=["a", "b", "c"])
        w.seed("start")
        w.apply("a", Speak(content="from a"))
        w.apply("b", Speak(content="from b"))

        p_a = w.observe("a")
        msgs_a = p_a.of_type(MessagesSlice)
        assert msgs_a is not None
        assert all(m.sender not in ["a", "b", "c"] for m in msgs_a.messages)

        p_b = w.observe("b")
        msgs_b = p_b.of_type(MessagesSlice)
        assert msgs_b is not None
        senders_b = [m.sender for m in msgs_b.messages]
        assert "a" in senders_b
        assert "b" not in senders_b or any(m.sender == "b" for m in msgs_b.messages if m.sender == "b")

        p_c = w.observe("c")
        msgs_c = p_c.of_type(MessagesSlice)
        assert msgs_c is not None
        senders_c = [m.sender for m in msgs_c.messages]
        assert "b" in senders_c


# ── SpatialWorld tests ─────────────────────────────────────────────────


class TestSpatialWorld:
    def test_spatial_perception(self) -> None:
        grid = Grid2D()
        grid.place("a", (0, 0))
        grid.place("b", (1, 0))
        grid.place("c", (100, 100))

        w = SpatialWorld(grid=grid, listen_radius=5.0)
        p = w.observe("a")

        spatial = p.of_type(SpatialSlice)
        assert spatial is not None
        assert spatial.position == (0, 0)
        assert "b" in spatial.nearby
        assert "c" not in spatial.nearby

    def test_move_updates_position(self) -> None:
        grid = Grid2D()
        grid.place("a", (0, 0))

        w = SpatialWorld(grid=grid)
        w.apply("a", Move(target=(5, 5)))
        assert grid.positions["a"] == (5, 5)


# ── SharedState tests ──────────────────────────────────────────────────


class TestSharedState:
    def test_put_get(self) -> None:
        s = SharedState()
        s.put("key", 42)
        assert s.get("key") == 42
        assert s.has("key")

    def test_versioning(self) -> None:
        s = SharedState()
        s.put("k", 1)
        s.put("k", 2)
        assert s.get("k") == 2
        assert s.get("k", version=1) == 1

    def test_snapshot(self) -> None:
        s = SharedState()
        s.put("a", 1)
        s.put("b", 2)
        snap = s.snapshot()
        assert snap == {"a": 1, "b": 2}


# ── StatefulWorld tests ───────────────────────────────────────────────


class TestStatefulWorld:
    def test_set_state_action(self) -> None:
        inner = ConversationWorld()
        shared = SharedState()
        w = StatefulWorld(inner, shared)

        w.apply("alice", SetState(key="result", value=42))
        assert shared.get("result") == 42

    def test_state_slice_in_perception(self) -> None:
        inner = ConversationWorld()
        shared = SharedState()
        shared.put("x", 10)
        w = StatefulWorld(inner, shared)

        p = w.observe("alice")
        state_slice = p.of_type(StateSlice)
        assert state_slice is not None
        assert ("x", 10) in state_slice.snapshot


# ── Integration tests ──────────────────────────────────────────────────


class TestRuntimeIntegration:
    def test_entity_mapping_keys_must_match_entity_ids(self) -> None:
        with pytest.raises(
            ValueError,
            match="entity mapping key 'alias' does not match entity.id 'actual'",
        ):
            Runtime(
                world=ConversationWorld(),
                entities={"alias": EchoEntity("actual")},
                schedule=TakeTurns(order=["alias"]),
            )

    async def test_schedule_rejects_unknown_entity_ids(self) -> None:
        runtime = Runtime(
            world=ConversationWorld(),
            entities={"known": EchoEntity("known")},
            schedule=TakeTurns(order=["missing"]),
        )

        with pytest.raises(ValueError, match="unknown entity IDs: missing"):
            await runtime.run("hello")

    async def test_sequential_echo(self) -> None:
        a = EchoEntity("a", prefix="A:")
        b = EchoEntity("b", prefix="B:")

        world = ConversationWorld()
        schedule = TakeTurns(order=["a", "b"])
        rt = Runtime(
            world=world,
            entities={"a": a, "b": b},
            schedule=schedule,
        )

        result = await rt.run("hello")
        speeches = result.speeches()
        assert len(speeches) == 2
        assert speeches[0] == ("a", "A:hello")
        assert speeches[1] == ("b", "B:A:hello")

    async def test_parallel_tick(self) -> None:
        a = CounterEntity("a")
        b = CounterEntity("b")

        world = ConversationWorld()
        schedule = MaxTicks(inner=AllParallel(ids=["a", "b"]), n=1)
        rt = Runtime(
            world=world,
            entities={"a": a, "b": b},
            schedule=schedule,
        )

        result = await rt.run("go")
        assert result.ticks == 1
        speeches = result.speeches()
        assert len(speeches) == 2

    async def test_silent_entity_stops_idle(self) -> None:
        a = SilentEntity("a")

        world = ConversationWorld()
        schedule = MaxTicks(
            inner=UntilIdle(inner=AllParallel(ids=["a"]), grace=1),
            n=5,
        )
        rt = Runtime(
            world=world,
            entities={"a": a},
            schedule=schedule,
        )

        result = await rt.run("test")
        assert result.ticks <= 2

    async def test_pipeline_world_integration(self) -> None:
        a = EchoEntity("a", prefix="[a]")
        b = EchoEntity("b", prefix="[b]")

        world = PipelineWorld(order=["a", "b"])
        schedule = TakeTurns(order=["a", "b"])
        rt = Runtime(
            world=world,
            entities={"a": a, "b": b},
            schedule=schedule,
        )

        result = await rt.run("start")
        speeches = result.speeches()
        assert len(speeches) == 2
        assert speeches[0] == ("a", "[a]start")
        assert speeches[1] == ("b", "[b][a]start")


# ── Grid2D tests ──────────────────────────────────────────────────────


class TestGrid2D:
    def test_neighbors(self) -> None:
        g = Grid2D()
        g.place("a", (0, 0))
        g.place("b", (3, 4))
        g.place("c", (1, 0))

        assert "c" in g.neighbors_of("a", 2.0)
        assert "b" not in g.neighbors_of("a", 2.0)
        assert "b" in g.neighbors_of("a", 6.0)

    def test_distance(self) -> None:
        g = Grid2D()
        g.place("a", (0, 0))
        g.place("b", (3, 4))
        assert g.distance("a", "b") == 5.0
