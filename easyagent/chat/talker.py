"""Talker protocol and built-in adapters.

The Talker protocol is the single unifying abstraction of the chat layer:
LLM agents, humans, sub-systems, and runtimes all implement it. Anything
that takes a ChatMessage and produces a ChatMessage (or chooses to stay
silent) is a Talker, and any container that holds Talkers should itself
be a Talker — see ``Orchestrator`` in ``easyagent.chat.orchestrator``.

Three adapters live here:

    LLMTalker   — wraps an existing ``BaseAgent`` (Agent / ReactAgent /
                  SkillAgent / SandboxAgent) so it joins the chat layer
                  without modification. Per-channel sessions keep
                  parallel conversations isolated.

    HumanTalker — pulls replies from an asyncio.Queue, so the human
                  speaks via UI, CLI, or a websocket without the
                  Orchestrator having to know.

    RuntimeTalker is defined in this module too once Step 9 lands; for
    now we only ship LLMTalker and HumanTalker.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol, runtime_checkable

from easyagent.chat.message import ChatMessage, Identity
from easyagent.chat.formatter import MultiAgentFormatter
from easyagent.model.schema import Message

if TYPE_CHECKING:
    from easyagent.agent.base import BaseAgent
    from easyagent.agent.session import AgentSession


__all__ = ["Talker", "LLMTalker", "HumanTalker", "RuntimeTalker", "is_talker"]


# ── Protocol ─────────────────────────────────────────────────────────────


@runtime_checkable
class Talker(Protocol):
    """Anything that can hold a turn in a multi-agent conversation.

    A Talker is responsible for its own internal state (memory, tools,
    sub-orchestration, …); the chat layer only requires it to:

      1. Expose a stable ``identity``.
      2. Produce a reply (or ``None`` for silence) when called.
      3. Accept observations (messages addressed to it without a
         requested reply) without producing output.

    Returning ``None`` from ``__call__`` is a first-class signal that
    the Talker is choosing not to speak this turn — it's not an error
    and it's not equivalent to an empty string. Orchestrators use this
    to drive idle-based stopping conditions.
    """

    identity: Identity

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str = "default",
    ) -> ChatMessage | None: ...

    async def observe(self, msg: ChatMessage) -> None: ...

    async def aclose(self) -> None: ...


# ── LLMTalker ────────────────────────────────────────────────────────────


class LLMTalker:
    """Adapter that lets an existing ``BaseAgent`` act as a Talker.

    One ``LLMTalker`` instance backs one identity, but it can participate
    in multiple channels simultaneously. Each channel gets its own
    ``AgentSession`` (and therefore its own memory and context window),
    created lazily on first use. This is how "alice talks in #design
    and #ops at the same time" works without state bleeding between
    rooms.

    The adapter does NOT modify the wrapped agent. It plugs three pieces
    together:

      - ``ChatMessage  →  Message``    : ``MultiAgentFormatter`` turns
                                         the channel's accumulated chat
                                         history into the LLM API
                                         message list. Until Step 3 we
                                         fall back to a minimal
                                         tag-prefix formatter so this
                                         module is independently usable.
      - ``BaseAgent.run`` is invoked with the latest incoming message
        as the active prompt; the agent's existing ReAct/Skill/Sandbox
        loop runs to completion.
      - ``str output  →  ChatMessage`` : the agent's final string is
                                         wrapped into a fresh
                                         ``ChatMessage`` carrying this
                                         talker's identity and an
                                         optional reply target.

    The wrapped agent's own ``name`` is overwritten on construction to
    match the talker's identity — keeping the two in sync prevents the
    formatter from confusing self-vs-other when looking at memory.
    """

    def __init__(
        self,
        agent: "BaseAgent",
        *,
        identity: Identity | str | None = None,
        formatter: MultiAgentFormatter | None = None,
        bus: "Any | None" = None,
    ) -> None:
        if isinstance(identity, str):
            identity = Identity(identity)
        elif identity is None:
            name = getattr(agent, "name", "") or "agent"
            identity = Identity(name)
        self.identity = identity
        # Keep the wrapped agent's display name aligned with our identity
        # so memory entries are tagged consistently. We mutate this on
        # purpose — the agent is "owned" by this talker after wrapping.
        # ``BaseAgent`` itself has no ``name`` attribute, but every
        # concrete subclass (``Agent`` and friends) does; setattr keeps
        # the type-checker out of the way without lying about the type.
        if hasattr(agent, "name"):
            setattr(agent, "name", identity.name)
        self._agent = agent
        # If the caller didn't pass a formatter, build one keyed on this
        # talker's name. ``session_for`` will install it onto each new
        # session's ``context`` slot, replacing whatever the agent's
        # default factory produced (typically ``SlidingWindowContext``).
        # That swap is the entire mechanism by which multi-agent
        # awareness reaches the underlying agent loop.
        self._formatter = formatter or MultiAgentFormatter(
            self_name=identity.name,
        )
        # Optional EventBus for fine-grained telemetry (LLMRespondedEvent /
        # ToolCalledEvent / ToolResultEvent / ...). Plumbed into each
        # per-channel ``AgentSession.event_bus`` so the underlying ReactAgent
        # emits its existing telemetry on this bus. The Orchestrator
        # auto-injects its own bus into members that don't have one set
        # — see ``Orchestrator.__post_init__``.
        self._bus = bus
        # channel → session. Lazily populated.
        self._sessions: dict[str, "AgentSession"] = {}

    # ── public API ──────────────────────────────────────────────────────

    @property
    def agent(self) -> "BaseAgent":
        return self._agent

    @property
    def bus(self) -> "Any | None":
        return self._bus

    def attach_bus(self, bus: "Any") -> None:
        """Set the bus and propagate to any already-created sessions.
        Called by the Orchestrator at construction time so existing
        callers don't have to remember to pass ``bus=`` to each Talker.
        """
        self._bus = bus
        for session in self._sessions.values():
            session.event_bus = bus

    def session_for(self, channel: str) -> "AgentSession":
        """Return (creating if necessary) the ``AgentSession`` backing
        this Talker's participation in ``channel``.

        The first time a channel is touched, we install a fresh
        ``MultiAgentFormatter`` clone as the session's context renderer.
        Cloning matters: each session needs its own formatter instance
        in case the user later mutates per-channel formatter settings.
        """
        session = self._sessions.get(channel)
        if session is None:
            session = self._agent.create_session()
            session.metadata["channel"] = channel
            session.context = self._formatter.clone()
            session.event_bus = self._bus    # ReactAgent telemetry → this bus
            self._sessions[channel] = session
        return session

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str | None = None,
    ) -> ChatMessage | None:
        # Resolve the channel: explicit kwarg wins, else use the message's
        # channel, else "default". The two should agree in practice; the
        # explicit kwarg lets the orchestrator force a channel even when
        # ``msg`` is None (i.e. the talker is being prompted to speak with
        # no new input — relying purely on prior observations).
        ch = channel or (msg.channel if msg else "default")
        session = self.session_for(ch)

        if msg is not None:
            await self._absorb(session, msg)

        # Drive the underlying agent. We use ``run_session`` directly
        # rather than ``agent.run`` so we can keep our own session across
        # turns instead of building a fresh one each call. The user_input
        # is empty because everything the agent needs is already in
        # session memory (either from observations or from the message
        # we just absorbed).
        loop_input = self._loop_input_for(msg)
        output = await self._drive_agent(session, loop_input)

        text = (output or "").strip()
        if not text or text.lower() == "max iterations reached":
            return None

        reply_to: str | frozenset[str]
        if msg is None or msg.is_broadcast:
            reply_to = "*"
        else:
            # Reply directly to the original sender by default.
            reply_to = frozenset({msg.sender.name})

        reply = ChatMessage(
            sender=self.identity,
            content=text,
            to=reply_to,
            channel=ch,
            role="assistant",
            reply_to=msg.id if msg is not None else None,
        )

        # Mirror the reply into our own session memory so subsequent
        # turns see "what I said last time" without having to round-trip
        # through the orchestrator. We tag with our own name so the
        # formatter recognises it as a self-turn next time.
        session.add_message(Message.assistant(text, name=self.identity.name))
        return reply

    async def observe(self, msg: ChatMessage) -> None:
        """Absorb a message into memory without generating a reply.

        Observations only land in the session's memory — they don't
        invoke the LLM. The next ``__call__`` on this channel will see
        them as part of the prompt context.
        """
        session = self.session_for(msg.channel)
        await self._absorb(session, msg)

    async def aclose(self) -> None:
        # Sessions own no external resources by default; subclasses with
        # sandboxes or background tasks should clean up here. Because
        # ``Agent.run`` already calls ``on_session_end`` on every run, we
        # don't fire it again per session — that would double-close.
        self._sessions.clear()

    # ── internals ───────────────────────────────────────────────────────

    async def _absorb(self, session: "AgentSession", msg: ChatMessage) -> None:
        """Write a ChatMessage into session memory.

        Other-talker messages land as ``role=user`` carrying the
        sender's ``name`` so ``MultiAgentFormatter`` can attribute them
        in the folded ``<history>`` block. We don't prefix the content
        with ``[name]`` — that's the formatter's job, not the absorbing
        talker's. Self-messages are dropped: the orchestrator already
        filters them, but this guards direct invocation paths.
        """
        if msg.sender.name == self.identity.name:
            return
        text = msg.text
        if not text:
            return
        if msg.role == "system":
            session.add_message(Message.system(text))
            return
        # Everyone else's contribution is a user-role message tagged
        # with the speaker's name. The formatter handles attribution
        # and folding from there.
        session.add_message(Message.user(text, name=msg.sender.name))

    def _loop_input_for(self, msg: ChatMessage | None) -> str:
        """The string handed to ``run_session`` as the active prompt.

        We've already written the incoming message into memory via
        ``_absorb``, so the loop input here is informational — the
        underlying agent will append it again as a user message, but
        that's fine: it serves as "this is the turn you must respond
        to" anchor. When ``msg`` is None the talker was prompted to
        speak with no new input; we hand the agent an empty string and
        rely on memory state.
        """
        if msg is None:
            return ""
        return msg.text

    async def _drive_agent(self, session: "AgentSession", user_input: str) -> str:
        """Run the agent's loop against ``session`` and return the final
        text output. We deliberately avoid ``agent.run`` because that
        method creates and tears down a fresh session each call; we want
        per-channel sessions to persist across turns.
        """
        from easyagent.agent.session import AgentStatus

        if user_input == "":
            # The agent's own ``run_session`` always appends a user
            # message; calling it with an empty string would inject a
            # blank turn that confuses the LLM. Instead we just step the
            # loop once with whatever's already in memory.
            session.iteration_count = 0
            session.loop_steps.clear()
            session.loop_state.clear()
            session.status = AgentStatus.RUNNING
            await self._agent.on_session_start(session)
            try:
                result = await self._agent.step(session)
                session.loop_steps.append(result)
                while not result.done:
                    result = await self._agent.step(session)
                    session.loop_steps.append(result)
            finally:
                await self._agent.on_session_end(session)
                session.status = AgentStatus.COMPLETED
            return result.output or session.final_output or ""

        # Normal path: hand the agent the new input and let its own
        # ``run_session`` machinery run.
        return await self._agent.run_session(session, user_input)


# ── HumanTalker ──────────────────────────────────────────────────────────


_HumanInputProvider = Callable[[ChatMessage | None, str], Awaitable[str | None]]
"""Async callable returning the human's reply text, or None for silence.

Receives ``(prompting_message, channel)`` so the UI layer can render
context. Returning ``None`` is the human's way to pass the turn.
"""


class HumanTalker:
    """Talker backed by a human.

    The human's reply is supplied via either:

      - an ``input_provider`` async callable (UI integration), or
      - a default-installed ``asyncio.Queue`` (test harnesses, simple
        terminal loops).

    HumanTalker has no memory of its own — humans are stateful in their
    own heads. Calls to ``observe`` are forwarded to an optional
    ``on_observe`` callback so the UI can display chatter without
    prompting a reply.
    """

    def __init__(
        self,
        identity: Identity | str = "user",
        *,
        input_provider: _HumanInputProvider | None = None,
        on_observe: Callable[[ChatMessage], Awaitable[None] | None] | None = None,
    ) -> None:
        if isinstance(identity, str):
            identity = Identity(identity, role="user")
        self.identity = identity
        self._input_provider = input_provider
        self._on_observe = on_observe
        self._queue: asyncio.Queue[str | None] | None = None
        if input_provider is None:
            # Default: pull replies from a queue. ``send_reply`` enqueues.
            self._queue = asyncio.Queue()

    # ── public API ──────────────────────────────────────────────────────

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str | None = None,
    ) -> ChatMessage | None:
        ch = channel or (msg.channel if msg else "default")
        text = await self._next_reply(msg, ch)
        if text is None or text == "":
            return None

        reply_to: str | frozenset[str]
        if msg is None or msg.is_broadcast:
            reply_to = "*"
        else:
            reply_to = frozenset({msg.sender.name})

        return ChatMessage(
            sender=self.identity,
            content=text,
            to=reply_to,
            channel=ch,
            role="user",
            reply_to=msg.id if msg is not None else None,
        )

    async def observe(self, msg: ChatMessage) -> None:
        if self._on_observe is None:
            return
        result = self._on_observe(msg)
        if asyncio.iscoroutine(result):
            await result

    async def aclose(self) -> None:
        if self._queue is not None:
            # Unblock anyone waiting for input.
            self._queue.put_nowait(None)

    # Convenience for the queue-based default mode.
    def send_reply(self, text: str | None) -> None:
        """Push the human's reply into the default queue. ``None`` =
        explicit silence for one turn."""
        if self._queue is None:
            raise RuntimeError(
                "HumanTalker was constructed with a custom input_provider; "
                "send_reply only works in queue mode."
            )
        self._queue.put_nowait(text)

    # ── internals ───────────────────────────────────────────────────────

    async def _next_reply(self, msg: ChatMessage | None, channel: str) -> str | None:
        if self._input_provider is not None:
            return await self._input_provider(msg, channel)
        assert self._queue is not None
        return await self._queue.get()


# ── RuntimeTalker ────────────────────────────────────────────────────────


class RuntimeTalker:
    """Adapter that lets a tick-based ``BaseRuntime`` act as a Talker.

    This is what makes the chat layer and the runtime layer composable
    in both directions: an ``Orchestrator`` can hold a ``RuntimeTalker``
    as a member (and the runtime's tick loop becomes "one turn" from
    the outside), and a runtime's seed events can be produced by a
    chat-layer ``Orchestrator``.

    The runtime is invoked once per ``__call__``: we translate the
    incoming ``ChatMessage`` into a seed ``MessageEvent``, run the
    runtime to completion, and pick its outbound message via the
    ``select_output`` callable (default: last MessageEvent in the
    runtime's record).

    Because runtimes already broadcast through their own ``EventBus``,
    we don't double-publish. ``observe`` writes the message into every
    session's memory directly so the next ``__call__`` sees it as
    context.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        identity: Identity | str | None = None,
        select_output: Callable[[Any], Any] | None = None,
    ) -> None:
        if isinstance(identity, str):
            identity = Identity(identity)
        elif identity is None:
            identity = Identity(getattr(runtime, "name", None) or "runtime")
        self.identity = identity
        self._runtime = runtime
        self._select_output = select_output or _default_runtime_output

    @property
    def runtime(self) -> Any:
        return self._runtime

    async def __call__(
        self,
        msg: ChatMessage | None = None,
        *,
        channel: str | None = None,
    ) -> ChatMessage | None:
        # Lazy imports keep the chat layer free of runtime-import cost
        # at module load — and let users skip the runtime layer entirely
        # if they only use chat presets.
        from easyagent.events.types import MessageEvent

        ch = channel or (msg.channel if msg else "default")

        seed_events: list[Any] = []
        if msg is not None:
            seed_events.append(
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

        result = await self._runtime.run(seed_events) if seed_events else await self._runtime.run()
        out_event = self._select_output(result)
        if out_event is None:
            return None

        # Pull text out of the runtime's MessageEvent. Runtimes might
        # emit a non-MessageEvent — in that case fall back to str().
        text = getattr(out_event, "content", None)
        if text is None:
            text = str(out_event)

        return ChatMessage(
            sender=self.identity,
            content=text,
            to="*",
            channel=ch,
            role="assistant",
            reply_to=msg.id if msg is not None else None,
            metadata={"runtime_stop_reason": getattr(result, "stop_reason", "")},
        )

    async def observe(self, msg: ChatMessage) -> None:
        """Write the message into every session's memory so all wrapped
        agents see it on their next turn. Also publishes a parallel
        ``MessageEvent`` on the runtime's bus so live subscribers
        observe it.
        """
        from easyagent.events.types import MessageEvent
        from easyagent.model.schema import Message as LLMMessage

        text = msg.text
        if not text:
            return

        for session in getattr(self._runtime, "sessions", {}).values():
            try:
                if msg.role == "system":
                    session.add_message(LLMMessage.system(text))
                else:
                    session.add_message(
                        LLMMessage.user(text, name=msg.sender.name)
                    )
            except Exception:  # noqa: BLE001
                # Sessions without writable memory are skipped silently.
                continue

        bus = getattr(self._runtime, "bus", None)
        if bus is not None:
            await bus.publish(
                MessageEvent(
                    sender=msg.sender.name,
                    content=text,
                    to=msg.to,
                    metadata={
                        **msg.metadata,
                        "channel": msg.channel,
                        "chat_message_id": msg.id,
                    },
                )
            )

    async def aclose(self) -> None:
        # Runtimes don't have a generic aclose; subclasses with
        # background tasks should override on the runtime side.
        pass


def _default_runtime_output(result: Any) -> Any:
    """Pick a runtime's outbound message: the last MessageEvent in its
    recorded events, or whatever ``result.messages[-1]`` returns.

    Custom runtimes can swap this via ``RuntimeTalker(select_output=...)``.
    """
    if result is None:
        return None
    msgs = getattr(result, "messages", None)
    if msgs:
        return msgs[-1]
    events = getattr(getattr(result, "state", None), "events", None)
    if events:
        from easyagent.events.types import MessageEvent

        for e in reversed(events):
            if isinstance(e, MessageEvent):
                return e
    return None


# ── light-touch type check helper ────────────────────────────────────────


def is_talker(obj: Any) -> bool:
    """Reliable Talker check.

    ``isinstance(obj, Talker)`` works because the protocol is
    ``runtime_checkable``, but it accepts any object with the right
    attribute names regardless of their types — too lax. This helper
    additionally requires ``identity`` to be an actual ``Identity``
    instance, which is what every chat-layer call site needs.

    Used by Step 5 (Orchestrator) and Step 7 (presets) to validate
    ``members`` containers.
    """
    return (
        hasattr(obj, "identity")
        and isinstance(getattr(obj, "identity", None), Identity)
        and callable(getattr(obj, "__call__", None))
        and callable(getattr(obj, "observe", None))
    )
