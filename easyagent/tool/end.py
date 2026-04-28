"""End / completion tool — the canonical way an agent says "I'm done".

A ``ReactAgent`` comes with this tool installed by default. The LLM
calls it when its work is finished; the ``data`` argument carries the
final delivery and becomes the agent's ``final_output``.

When called:

  1. ``data`` is stored on ``session.loop_state["__early_exit__"]`` so
     the ReAct loop terminates at its next checkpoint.
  2. A :class:`StopEvent` is published on the bus, observable by anyone
     subscribing for logging / debugging / replay.
"""

from __future__ import annotations

from typing import Any


class EndTool:
    """The agent's "I'm done" tool.

    ``data`` is the final answer the caller (typically a user, or a
    chat-layer ``LLMTalker``) will read. After ``end()`` the loop stops
    immediately, so ``data`` must be self-contained — anything written
    in the assistant message content alongside ``end()`` is discarded.
    """

    type = "function"
    name = "end"
    description = (
        "Call this when you have finished your task. The `data` argument is "
        "your final delivery — everything the caller needs. After this call "
        "your loop terminates immediately, so put the FULL answer in `data`. "
        "Do NOT also write the answer in your message content — content is "
        "discarded once `end` is called."
    )
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": (
                    "Your final, self-contained answer. The recipient does "
                    "not see your internal reasoning or tool calls — be "
                    "explicit and complete."
                ),
            }
        },
        "required": ["data"],
    }

    def init(self) -> None:
        pass

    async def execute(
        self,
        data: str,
        *,
        session: Any | None = None,
        **kwargs: Any,
    ) -> str:
        if session is None:
            return "Error: end tool requires a session context."
        session.loop_state["__early_exit__"] = data
        if session.event_bus is not None:
            from easyagent.events.types import StopEvent

            await session.event_bus.publish(
                StopEvent(
                    session_id=session.session_id,
                    reason="task complete",
                    data=data,
                )
            )
        return "Task marked complete."
