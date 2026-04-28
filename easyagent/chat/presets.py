"""User-facing presets for common multi-agent patterns.

Each preset is just a thin factory over ``Orchestrator`` with its
strategies pre-configured. Users start here:

    final = await sequential([researcher, writer], "moon overview")

If a preset doesn't fit, drop down to ``Orchestrator(...)`` directly
and pick strategies à la carte.
"""

from __future__ import annotations

import asyncio
from copy import copy
from typing import TYPE_CHECKING, Iterable

from easyagent.chat.message import ChatMessage, Identity
from easyagent.chat.orchestrator import ManualSession, Orchestrator
from easyagent.chat.strategies.routing import Broadcast, Direct
from easyagent.chat.strategies.stop import (
    AfterAllSpoken,
    AnyOf,
    Idle,
    MaxRounds,
    OnPredicate,
)
from easyagent.chat.strategies.summarize import (
    Aggregate,
    ByJudge,
    LastMessage,
)
from easyagent.chat.strategies.turn_taking import (
    Conducted,
    Manual,
    Reactive,
)
from easyagent.chat.talker import Talker
from easyagent.chat.turn_context import TurnContext

if TYPE_CHECKING:
    from easyagent.events.bus import EventBus


__all__ = ["sequential", "fanout", "debate", "chatroom", "groupchat"]


def _members_dict(talkers: Iterable[Talker]) -> dict[str, Talker]:
    """Build a name → Talker map and validate uniqueness."""
    out: dict[str, Talker] = {}
    for t in talkers:
        name = t.identity.name
        if name in out:
            raise ValueError(
                f"duplicate talker name {name!r} — each Talker in a preset "
                f"must have a unique identity"
            )
        out[name] = t
    return out


def _normalize_seed(
    seed: ChatMessage | str | None,
    *,
    channel: str = "default",
    to: str | frozenset[str] = "*",
) -> ChatMessage | None:
    """Accept ``str`` for ergonomics; promote to a user-role ChatMessage."""
    if seed is None:
        return None
    if isinstance(seed, str):
        return ChatMessage(
            sender=Identity("user", role="user"),
            content=seed,
            to=to,
            channel=channel,
            role="user",
        )
    return seed


# ── sequential ───────────────────────────────────────────────────────────


async def sequential(
    talkers: Iterable[Talker],
    seed: ChatMessage | str | None = None,
    *,
    bus: "EventBus | None" = None,
    channel: str = "default",
    identity: Identity | str = "sequential",
) -> ChatMessage | None:
    """Run talkers in order: A speaks, then B sees A's reply and speaks,
    then C sees A+B's replies and speaks, ...

    Each talker speaks exactly once. The pipeline's output is the last
    talker's reply. Used for "researcher → writer → editor" style
    flows where the order is known up front.

    Returns ``None`` if every talker stays silent.
    """
    members = _members_dict(talkers)
    order = list(members.keys())
    if not order:
        return None
    orch = Orchestrator(
        members=members,
        # We use Broadcast (not Pipeline) routing here so each talker
        # sees the full prior history, not just their immediate
        # predecessor's output. That matches AgentScope's
        # ``sequential_pipeline`` semantics, which is what users
        # familiar with that library will expect.
        routing=Broadcast(),
        turn_taking=Conducted(order=order),
        stop=AfterAllSpoken(members=order),
        summarize=LastMessage(),
        identity=_to_identity(identity),
        bus=bus,
    )
    return await orch(_normalize_seed(seed, channel=channel), channel=channel)


# ── fanout ───────────────────────────────────────────────────────────────


async def fanout(
    talkers: Iterable[Talker],
    seed: ChatMessage | str | None = None,
    *,
    gather: bool = True,
    bus: "EventBus | None" = None,
    channel: str = "default",
    aggregate: bool = False,
    identity: Identity | str = "fanout",
) -> list[ChatMessage]:
    """Send the same seed to every talker, collect their replies.

    By default returns a list of ``ChatMessage`` (or empty list if all
    silent), one per talker — order matches the input.

    ``gather=True`` (default) runs talkers concurrently via
    ``asyncio.gather``. ``gather=False`` runs them sequentially.

    ``aggregate=True`` instead returns a single ``ChatMessage`` whose
    content concatenates every reply (using the ``Aggregate`` summarize
    strategy under the hood) — convenient when feeding the result into
    a downstream pipeline.
    """
    members = _members_dict(talkers)
    if not members:
        return [] if not aggregate else []

    seed_msg = _normalize_seed(seed, channel=channel)

    if aggregate:
        orch = Orchestrator(
            members=members,
            routing=Broadcast(),
            turn_taking=Conducted(order=list(members.keys())),
            stop=AfterAllSpoken(),
            summarize=Aggregate(),
            identity=_to_identity(identity),
            bus=bus,
        )
        out = await orch(seed_msg, channel=channel)
        return [out] if out is not None else []

    # Direct concurrent / sequential invocation — no Orchestrator
    # because ``fanout`` is supposed to be a thin function. Bus
    # observability is handled by publishing manually.
    async def call_one(t: Talker) -> ChatMessage | None:
        # Each talker receives an independent COPY of the seed (we
        # deliberately don't share metadata mutations across them).
        seed_for_t = (
            ChatMessage(
                sender=seed_msg.sender,
                content=seed_msg.content,
                to=copy(seed_msg.to) if isinstance(seed_msg.to, frozenset) else seed_msg.to,
                channel=seed_msg.channel,
                role=seed_msg.role,
                metadata=dict(seed_msg.metadata),
            )
            if seed_msg is not None
            else None
        )
        reply = await t(seed_for_t, channel=channel)
        if reply is not None and bus is not None:
            from easyagent.events.types import MessageEvent

            await bus.publish(
                MessageEvent(
                    sender=reply.sender.name,
                    content=reply.text,
                    to=reply.to,
                    metadata={
                        **reply.metadata,
                        "channel": reply.channel,
                        "chat_message_id": reply.id,
                    },
                )
            )
        return reply

    talker_list = list(members.values())
    if gather:
        replies = await asyncio.gather(*(call_one(t) for t in talker_list))
    else:
        replies = [await call_one(t) for t in talker_list]
    return [r for r in replies if r is not None]


# ── debate ───────────────────────────────────────────────────────────────


async def debate(
    talkers: Iterable[Talker],
    *,
    judge: Talker,
    seed: ChatMessage | str | None = None,
    max_rounds: int = 4,
    bus: "EventBus | None" = None,
    channel: str = "default",
    identity: Identity | str = "debate",
    instruction: str | None = None,
) -> ChatMessage | None:
    """Round-robin debate among ``talkers`` with ``judge`` summarising.

    Each round, every talker speaks once (in registration order) — the
    others see each speech as it arrives. After ``max_rounds`` (or
    earlier if the judge marks ``finished=True`` in metadata), the
    judge produces the conclusion.

    The judge is NOT a member — it doesn't participate in the debate,
    it only synthesises the conclusion at the end. Pass it separately.

    The output is the judge's verdict, sender re-badged as the
    orchestrator (``identity``) so a wrapping pipeline doesn't see
    the judge's name leaking through.
    """
    members = _members_dict(talkers)
    if not members:
        return None
    order = list(members.keys())

    # Allow members to short-circuit the debate by setting
    # metadata['finished']=True on their reply.
    def _someone_finished(ctx: "TurnContext") -> bool:
        last = ctx.last_message
        return bool(last and last.metadata.get("finished"))

    summarize = ByJudge(judge=judge)
    if instruction is not None:
        summarize.instruction = instruction

    orch = Orchestrator(
        members=members,
        routing=Broadcast(),
        turn_taking=Conducted(order=order * max_rounds),
        stop=AnyOf(
            conditions=[
                MaxRounds(len(order) * max_rounds),
                OnPredicate(_someone_finished, reason="member_finished"),
            ]
        ),
        summarize=summarize,
        identity=_to_identity(identity),
        bus=bus,
    )
    return await orch(_normalize_seed(seed, channel=channel), channel=channel)


# ── chatroom ─────────────────────────────────────────────────────────────


def chatroom(
    talkers: Iterable[Talker],
    *,
    announcement: ChatMessage | str | None = None,
    bus: "EventBus | None" = None,
    channel: str = "default",
    identity: Identity | str = "chatroom",
) -> ManualSession:
    """Manual-mode group chat — AgentScope ``MsgHub`` equivalent.

    Returns an ``async with`` context. Inside the block, you call
    members directly (``await room.alice()``); their replies are
    automatically forwarded to peers. The orchestrator does not
    auto-loop — turn order is up to you.

    Usage:
        async with chatroom([alice, bob], announcement="welcome") as room:
            await room.alice()
            await room.bob()
    """
    members = _members_dict(talkers)
    orch = Orchestrator(
        members=members,
        routing=Broadcast(),
        turn_taking=Manual(),
        # No stop / summarize matters — the loop never runs.
        identity=_to_identity(identity),
        bus=bus,
    )
    return orch.session(
        channel=channel,
        announcement=_normalize_seed(announcement, channel=channel),
    )


# ── groupchat ────────────────────────────────────────────────────────────


def groupchat(
    talkers: Iterable[Talker],
    *,
    routing: str = "direct",
    stop: object | None = None,
    max_rounds: int = 16,
    bus: "EventBus | None" = None,
    identity: Identity | str = "groupchat",
) -> Orchestrator:
    """Auto-loop reactive group chat — addressees implicitly speak next.

    ``routing="direct"`` (default) honours each message's ``to`` field
    (talkers can address peers by name). ``routing="broadcast"`` makes
    every reply visible to everyone, falling back to round-robin for
    speaker selection.

    ``stop`` defaults to ``AnyOf([Idle(grace=1), MaxRounds(max_rounds)])``
    — keep going while anyone has more to say, but always cap turns
    so a chatty population can't loop forever.
    """
    members = _members_dict(talkers)
    if routing == "direct":
        r = Direct()
    elif routing == "broadcast":
        r = Broadcast()
    else:
        raise ValueError(
            f"groupchat routing must be 'direct' or 'broadcast', got {routing!r}"
        )
    default_stop = AnyOf(conditions=[Idle(grace=1), MaxRounds(max_rounds)])
    return Orchestrator(
        members=members,
        routing=r,
        turn_taking=Reactive(),
        stop=stop or default_stop,
        summarize=LastMessage(),
        identity=_to_identity(identity),
        bus=bus,
    )


# ── helpers ──────────────────────────────────────────────────────────────


def _to_identity(value: Identity | str) -> Identity:
    if isinstance(value, Identity):
        return value
    return Identity(value)
