"""TeamEntity — wraps an inner Runtime as a single Entity.

This enables recursive composition: a ``debate`` runtime with alice
and bob can be wrapped as one Entity inside a ``sequential`` pipeline.
The team's act() seeds the inner runtime with the last incoming
message, runs it, and returns the final speech as its own action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyagent.core.types import Action, MessagesSlice, Perception, Speak

if TYPE_CHECKING:
    from easyagent.core.runtime import Runtime

__all__ = ["TeamEntity"]


class TeamEntity:
    """A full Runtime masquerading as a single Entity."""

    def __init__(self, entity_id: str, runtime: "Runtime") -> None:
        self._id = entity_id
        self._runtime = runtime

    @property
    def id(self) -> str:
        return self._id

    async def act(self, perception: Perception) -> Action | None:
        msg_slice = perception.of_type(MessagesSlice)
        if msg_slice is None or not msg_slice.messages:
            return None

        last_msg = msg_slice.messages[-1]
        result = await self._runtime.run(last_msg.content, sender=last_msg.sender)

        speech = result.last_speech
        if speech is None:
            return None
        return Speak(content=speech)
