"""Orchestrator: the multi-Talker container.

The Orchestrator is what makes the chat layer compositional. A
``ChatMessage`` flows in, the orchestrator drives a turn loop based
on its four strategies, then a single ``ChatMessage`` flows out — and
because the orchestrator itself implements the Talker protocol, that
output can feed straight into another orchestrator. Nesting works
without any special API.

    seed ──▶  Orchestrator(routing, turn_taking, stop, summarize)  ──▶  reply
                       │     │           │              │
                       │     │           │              └─ Q6: what's the answer?
                       │     │           └─ Q4: when do we stop?
                       │     └─ Q2: who speaks next?
                       └─ Q3: who hears each message?

The class is configurable for the 99% case; for "manual" turn taking
(``chatroom`` preset) the same class is used inside an async context
manager (``Orchestrator.session()`` / ``ManualSession``) that wires
up subscribers but never auto-loops.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping

from easyagent.chat.message import ChatMessage, Identity
from easyagent.chat.strategies.routing import Broadcast, Routing
from easyagent.chat.strategies.stop import Idle, MaxRounds, StopCondition
from easyagent.chat.strategies.summarize import LastMessage, Summarize
from easyagent.chat.strategies.turn_taking import RoundRobin, TurnTaking
from easyagent.chat.talker import Talker, is_talker
from easyagent.chat.turn_context import TurnContext

if TYPE_CHECKING:
    from easyagent.chat.shared_state import SharedState
    from easyagent.events.bus import EventBus


__all__ = ["Orchestrator", "ManualSession"]


@dataclass
class Orchestrator:
    """Driver for a multi-Talker conversation.

    Args:
        members:      Talkers participating, keyed by name. Names must
                      be unique and match each Talker's identity.
        routing:      Decides who hears each message (default Broadcast).
        turn_taking:  Decides who speaks next (default RoundRobin).
        stop:         Halts the loop (default ``MaxRounds(8) | Idle(1)``).
        summarize:    Builds the message returned to the caller
                      (default LastMessage).
        identity:     The orchestrator's own Identity. Used as the
                      sender of the produced message so callers see a
                      stable container name regardless of who spoke
                      last internally.
        bus:          Optional EventBus for observability. When set,
                      every routed message also publishes a
                      ``MessageEvent``. The bus is *not* the transport
                      path — it's a side channel.
        shared_state: Optional blackboard for state-based collaboration.

    The defaults give a sensible "small group, polite chat" baseline
    so users can construct ``Orchestrator(members=...)`` without
    spelling out every strategy.
    """

    members: Mapping[str, Talker]
    routing: Routing = field(default_factory=Broadcast)
    turn_taking: TurnTaking | None = None
    stop: StopCondition | None = None
    summarize: Summarize = field(default_factory=LastMessage)
    identity: Identity = field(default_factory=lambda: Identity("orchestrator"))
    bus: "EventBus | None" = None
    shared_state: "SharedState | None" = None

    def __post_init__(self) -> None:
        for name, m in self.members.items():
            if not is_talker(m):
                raise TypeError(
                    f"member {name!r} is not a Talker (got {type(m).__name__})"
                )
            if m.identity.name != name:
                # We tolerate the mismatch but warn loudly via assertion
                # message — the chat layer assumes name == identity.name
                # for routing and folding to work consistently.
                raise ValueError(
                    f"member key {name!r} disagrees with identity "
                    f"{m.identity.name!r}; align them before constructing "
                    f"the Orchestrator"
                )
            # Auto-plumb the orchestrator's bus into every member that
            # didn't bring its own. This is what lets ReactAgent-level
            # telemetry (LLMRespondedEvent / ToolCalledEvent / ...) flow
            # to the same bus the user is subscribing to. We only do
            # this for ``LLMTalker`` (it has ``attach_bus``); other
            # Talker implementations decide for themselves whether they
            # care about a bus.
            if (
                self.bus is not None
                and getattr(m, "bus", None) is None
                and hasattr(m, "attach_bus")
            ):
                m.attach_bus(self.bus)  # type: ignore[attr-defined]
        # Sensible defaults applied here rather than via field default_factory
        # so they can introspect ``members`` if needed later.
        if self.turn_taking is None:
            self.turn_taking = RoundRobin()
        if self.stop is None:
            from easyagent.chat.strategies.stop import AnyOf

            self.stop = AnyOf(conditions=[MaxRounds(8), Idle(grace=1)])

    # ── Talker protocol ─────────────────────────────────────────────────

    async def __call__(
        self,
        msg: ChatMessage | str | None = None,
        *,
        channel: str | None = None,
    ) -> ChatMessage | None:
        """Drive the turn loop and return the orchestrator's outbound
        message. Implements the Talker protocol — orchestrators nest
        natively because of this signature.

        For ergonomics, ``msg`` may also be a plain string; it's
        promoted to a user-role ``ChatMessage`` from a synthetic
        ``"user"`` identity. Talkers calling each other should pass
        a real ``ChatMessage`` so identity/threading info survives.
        """
        if isinstance(msg, str):
            msg = ChatMessage(
                sender=Identity("user", role="user"),
                content=msg,
                role="user",
                channel=channel or "default",
            )
        ch = channel or (msg.channel if msg else "default")
        ctx = TurnContext(
            members=dict(self.members),
            channel=ch,
            history=[],
            bus=self.bus,
            shared=self.shared_state,
        )

        # 1. Seed: route, observe, append to history.
        if msg is not None:
            await self._deliver(ctx, msg, exclude_sender=True)
            ctx.history.append(msg)
            await self._publish_to_bus(msg)

        # 2. Auto-loop: turn_taking → speaker → reply → route.
        # Manual mode short-circuits because turn_taking returns None
        # immediately, so this is a no-op without special-casing.
        assert self.turn_taking is not None and self.stop is not None
        while True:
            stop_now, reason = self.stop.check(ctx)
            if stop_now:
                ctx.metadata["stop_reason"] = reason
                break

            speaker_name = await self.turn_taking.next(ctx)
            if speaker_name is None:
                ctx.metadata["stop_reason"] = "turn_taking_exhausted"
                break
            if speaker_name not in self.members:
                # Strategy returned a name we don't recognise. Treat as
                # silence rather than crashing — the strategy might be
                # confused, but we should fail soft.
                ctx.idle_rounds += 1
                ctx.round_index += 1
                continue

            speaker = self.members[speaker_name]
            try:
                reply = await speaker(channel=ch)
            except Exception as exc:  # noqa: BLE001
                ctx.metadata["error"] = repr(exc)
                ctx.metadata["stop_reason"] = "speaker_error"
                break

            ctx.round_index += 1

            if reply is None:
                ctx.idle_rounds += 1
                continue
            ctx.idle_rounds = 0

            ctx.history.append(reply)
            await self._publish_to_bus(reply)
            # Route to other members so they get the new message in
            # their memory before potentially being asked to speak next.
            await self._deliver(ctx, reply, exclude_sender=True)

        # 3. Summarize: produce the orchestrator's outbound message.
        out = await self.summarize.produce(ctx, self.identity)
        if out is not None and "stop_reason" in ctx.metadata:
            # Surface the stop reason on the outbound metadata so the
            # caller (often a wrapping pipeline or a UI) can introspect
            # why the conversation ended.
            out = out.with_metadata(stop_reason=ctx.metadata["stop_reason"])
        return out

    async def observe(self, msg: ChatMessage) -> None:
        """When the orchestrator is itself a member of an outer
        orchestrator, the outer one calls ``observe`` to seed it with
        context messages (e.g. announcements). We forward to all
        internal members per the routing policy.

        Note that ``observe`` must NOT trigger a turn loop — observing
        is the chat-layer's read-only contract. To actually produce
        output, the outer orchestrator must call ``__call__``.
        """
        ctx = TurnContext(
            members=dict(self.members),
            channel=msg.channel,
            history=[],
            bus=self.bus,
            shared=self.shared_state,
        )
        await self._deliver(ctx, msg, exclude_sender=True)

    async def aclose(self) -> None:
        # Orchestrators don't own external resources directly — but
        # nothing stops users from using ``aclose`` to tear down their
        # member talkers transitively. The default closes everyone.
        for m in self.members.values():
            try:
                await m.aclose()
            except Exception:  # noqa: BLE001
                pass

    # ── Manual mode (``chatroom`` preset) ───────────────────────────────

    def session(
        self,
        *,
        channel: str = "default",
        announcement: ChatMessage | None = None,
    ) -> "ManualSession":
        """Open a manual-mode interaction context.

        Inside the ``async with`` block, members are subscribed to each
        other's replies via the routing policy (so calling
        ``await alice(...)`` automatically forwards alice's output to
        bob and carol's memory). The Orchestrator does NOT auto-loop;
        the caller drives turn order manually. This is the AgentScope
        ``MsgHub`` pattern, expressed within the same Orchestrator
        primitive that powers everything else.

        ``turn_taking`` should be ``Manual()`` for this mode; if it
        isn't, the auto-loop is still suppressed inside the ``with``
        block but resumes if the caller separately invokes
        ``orch(seed)``.
        """
        return ManualSession(self, channel=channel, announcement=announcement)

    # ── internals ───────────────────────────────────────────────────────

    async def _deliver(
        self,
        ctx: TurnContext,
        msg: ChatMessage,
        *,
        exclude_sender: bool,
    ) -> None:
        targets = self.routing.targets(msg, ctx)
        if exclude_sender:
            targets = [t for t in targets if t != msg.sender.name]
        # Concurrent delivery is safe: each Talker's ``observe`` writes
        # only to its own session memory. We use ``asyncio.gather`` to
        # avoid serialising N independent IO-free writes.
        coros = []
        for name in targets:
            member = self.members.get(name)
            if member is None:
                continue
            coros.append(member.observe(msg))
        if coros:
            await asyncio.gather(*coros)

    async def _publish_to_bus(self, msg: ChatMessage) -> None:
        if self.bus is None:
            return
        # Lazy import to avoid runtime-layer dependency at module load.
        from easyagent.events.types import MessageEvent

        # Translate ChatMessage → MessageEvent. The bus is observability-
        # only, so any field we can't represent (e.g. channel) goes into
        # metadata rather than getting lost.
        await self.bus.publish(
            MessageEvent(
                sender=msg.sender.name,
                content=msg.text,
                to=msg.to,
                metadata={
                    **msg.metadata,
                    "channel": msg.channel,
                    "chat_message_id": msg.id,
                },
            )
        )


# ── ManualSession ────────────────────────────────────────────────────────


class ManualSession:
    """``async with`` wrapper for manual-mode orchestration.

    Inside the block, members are accessed via ``session.alice`` /
    ``session["alice"]`` — these are *wrapped* versions that forward
    replies to peers automatically. Calling the raw underlying member
    still works but skips routing.

    The wrappers are ordinary callables, so we sidestep the trap that
    setting ``instance.__call__ = ...`` does NOT intercept
    ``await instance(...)`` (Python resolves ``__call__`` through the
    class, not the instance).

    Used by the ``chatroom`` preset.
    """

    def __init__(
        self,
        orch: "Orchestrator",
        *,
        channel: str,
        announcement: ChatMessage | None,
    ) -> None:
        self._orch = orch
        self._channel = channel
        self._announcement = announcement
        self._wrapped: dict[str, "_MemberProxy"] = {}

    async def __aenter__(self) -> "ManualSession":
        for name, member in self._orch.members.items():
            self._wrapped[name] = _MemberProxy(member, self)
        if self._announcement is not None:
            await self.broadcast(self._announcement)
        return self

    async def __aexit__(self, *exc_info) -> None:
        self._wrapped.clear()

    @property
    def channel(self) -> str:
        return self._channel

    @property
    def members(self) -> dict[str, "_MemberProxy"]:
        return dict(self._wrapped)

    def __getattr__(self, name: str) -> "_MemberProxy":
        # __getattr__ only fires for attributes not found normally,
        # so this never shadows the legitimate attrs above.
        try:
            return self._wrapped[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, name: str) -> "_MemberProxy":
        return self._wrapped[name]

    async def broadcast(self, msg: ChatMessage) -> None:
        """Send a system/user announcement to every member without
        producing a reply. Equivalent to MsgHub announcements."""
        coros = [m.observe(msg) for m in self._orch.members.values()]
        if coros:
            await asyncio.gather(*coros)


class _MemberProxy:
    """Callable proxy installed by ``ManualSession`` that forwards
    replies to peers via the orchestrator's routing policy.

    Mirrors the Talker protocol (``identity``, ``__call__``,
    ``observe``, ``aclose``), so a proxy is itself a Talker.
    """

    def __init__(self, inner: Talker, session: ManualSession) -> None:
        self._inner = inner
        self._session = session

    @property
    def identity(self) -> Identity:
        return self._inner.identity

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str | None = None,
    ) -> ChatMessage | None:
        ch = channel or self._session.channel
        reply = await self._inner(msg, channel=ch)
        if reply is None:
            return None
        orch = self._session._orch
        ctx = TurnContext(
            members=dict(orch.members),
            channel=ch,
            history=[reply],
            bus=orch.bus,
            shared=orch.shared_state,
        )
        await orch._deliver(ctx, reply, exclude_sender=True)
        await orch._publish_to_bus(reply)
        return reply

    async def observe(self, msg: ChatMessage) -> None:
        await self._inner.observe(msg)

    async def aclose(self) -> None:
        await self._inner.aclose()
