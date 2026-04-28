"""User-facing conversation primitives for the chat layer.

``Identity`` and ``ChatMessage`` are the two data classes users handle when
working with multi-agent flows through ``easyagent.chat``. They sit *above*
the LLM-API protocol layer (``easyagent.model.schema.Message``) and *above*
the runtime event layer (``easyagent.events.types.MessageEvent``):

    user code  ──▶  ChatMessage   (this file)
                       │
                       │ MultiAgentFormatter
                       ▼
                    Message       (LLM API call)

    user code  ──▶  ChatMessage   (this file)
                       │
                       │ chat→bus bridge (observability only)
                       ▼
                    MessageEvent  (EventBus)

The chat layer never asks users to construct ``Message`` or ``MessageEvent``
themselves; those types stay internal to their respective layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4


__all__ = ["Identity", "ChatMessage", "BROADCAST"]


BROADCAST: Literal["*"] = "*"
"""Sentinel value for ``ChatMessage.to`` meaning "everyone in the channel"."""


# ── Identity ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Identity:
    """Stable identity of a Talker within a channel.

    ``name`` must be unique within any channel the talker participates in;
    a Talker reuses one ``Identity`` across all its messages.

    ``role`` is a coarse classification used by formatters and routers
    (``"agent"`` / ``"user"`` / ``"system"`` / ``"tool"`` or any custom
    label). It does NOT map directly onto LLM-API roles — that mapping is
    the formatter's job.

    ``aliases`` lets a Talker answer to multiple names (handy when a user
    types "@bot" but the registered name is "assistant"). Routing matches
    against ``name`` first, then ``aliases``.
    """

    name: str
    role: str = "agent"
    aliases: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Identity.name must be a non-empty string")
        # Make sure aliases is the canonical frozenset even if a list/set
        # was passed (frozen=True means we have to bypass __setattr__).
        if not isinstance(self.aliases, frozenset):
            object.__setattr__(self, "aliases", frozenset(self.aliases))

    def matches(self, candidate: str) -> bool:
        """True if ``candidate`` refers to this identity by name or alias."""
        return candidate == self.name or candidate in self.aliases


# ── ChatMessage ──────────────────────────────────────────────────────────


_VALID_ROLES = ("user", "assistant", "system", "tool")


@dataclass
class ChatMessage:
    """One utterance in a multi-agent conversation.

    Carries enough context that the message alone — without external
    subscription state — tells the framework who said it, who should hear
    it, in which conversation, and in reply to what.

    Fields:
        sender: Who is speaking (an ``Identity``).
        content: Either a plain string or a list of content blocks
            (``[{"type": "text", "text": ...}, {"type": "image_url", ...}]``)
            mirroring the convention used by ``model.schema.Message``.
        to: Routing destination. ``"*"`` for broadcast (default), a single
            recipient name, or a collection of names. Convenient input
            forms (``str`` / ``set`` / ``list`` / ``tuple``) are coerced
            to either the ``"*"`` literal or a ``frozenset[str]`` so
            downstream code can pattern-match without re-parsing.
        channel: Conversation/room/thread name. Memory and routing scope
            messages by channel, so a single Talker can participate in
            multiple parallel conversations without bleed-through.
        role: LLM-API style role hint. Most chat-layer messages produced
            by Talkers are ``"assistant"``; seed messages from the human
            invoker are ``"user"``. ``"system"`` and ``"tool"`` are
            allowed for completeness.
        reply_to: Optional id of the message this one replies to —
            useful for threading and for ``Summarize`` strategies that
            traverse causal chains.
        id: Stable identifier (uuid4). Auto-generated; supply explicitly
            only when round-tripping through serialization.
        metadata: Free-form bag for structured-output payloads, judge
            verdicts, scores, etc. Strategies that need extra signal
            (``OnPredicate``, ``ByJudge``, ``StopWhenMessageMatches``)
            read from here.

    The ``__post_init__`` normalisation is what lets users write any of:

        ChatMessage(..., to="*")              # broadcast
        ChatMessage(..., to="bob")            # single recipient (str)
        ChatMessage(..., to={"alice", "bob"}) # subgroup (set)
        ChatMessage(..., to=["alice", "bob"]) # subgroup (list)

    and have downstream code see only the canonical forms ``"*"`` or
    ``frozenset[str]``.
    """

    sender: Identity
    content: str | list[dict[str, Any]]
    to: (
        Literal["*"]
        | str
        | frozenset[str]
        | set[str]
        | list[str]
        | tuple[str, ...]
    ) = BROADCAST
    channel: str = "default"
    role: Literal["user", "assistant", "system", "tool"] = "assistant"
    reply_to: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce ``to`` into one of the two canonical forms:
        #   "*"            -> stays "*"
        #   "alice"        -> frozenset({"alice"})
        #   {"a","b"}      -> frozenset({"a","b"})
        if isinstance(self.to, str):
            if self.to != BROADCAST:
                self.to = frozenset({self.to})
        elif isinstance(self.to, (set, list, tuple)):
            self.to = frozenset(self.to)
        elif not isinstance(self.to, frozenset):
            raise TypeError(
                f"ChatMessage.to must be '*', a name, or a collection of names, "
                f"got {type(self.to).__name__}"
            )

        if self.role not in _VALID_ROLES:
            raise ValueError(
                f"ChatMessage.role must be one of {_VALID_ROLES}, got {self.role!r}"
            )

        if not isinstance(self.sender, Identity):
            raise TypeError(
                f"ChatMessage.sender must be an Identity, got {type(self.sender).__name__}"
            )

    # ── convenience accessors ───────────────────────────────────────────

    @property
    def is_broadcast(self) -> bool:
        """True if this message is addressed to everyone in the channel."""
        return self.to == BROADCAST

    @property
    def text(self) -> str:
        """Best-effort plain-text view of ``content``.

        Strings pass through unchanged; block lists concatenate ``text``
        blocks with newlines (mirrors the lazy approach in
        ``model.schema.content_to_text``). Use this for logging, history
        folding, and predicate matching — not for LLM API payloads.
        """
        if isinstance(self.content, str):
            return self.content
        parts: list[str] = []
        for block in self.content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif "text" in block:
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p)

    def visible_to(self, name: str) -> bool:
        """Whether a Talker named ``name`` should receive this message.

        Senders never receive their own messages — the orchestrator filters
        ``sender.name`` out before calling ``observe``; this method only
        answers the routing question, not the loopback question.
        """
        if self.is_broadcast:
            return True
        assert isinstance(self.to, frozenset)
        return name in self.to

    def with_metadata(self, **patch: Any) -> "ChatMessage":
        """Return a copy with ``metadata`` shallow-merged. Cheap and pure
        — used by strategies (``ByJudge``, ``Selected``) that want to
        annotate a message without mutating shared state."""
        merged = {**self.metadata, **patch}
        return ChatMessage(
            sender=self.sender,
            content=self.content,
            to=self.to,
            channel=self.channel,
            role=self.role,
            reply_to=self.reply_to,
            id=self.id,
            metadata=merged,
        )
