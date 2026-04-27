"""End / completion tool — the canonical way an agent says "I'm done".

A ReactAgent comes with this tool installed by default. The LLM calls it
when its work is finished. The ``data`` argument carries the final
delivery (or, in a pipeline, the handoff payload for the next agent —
same mechanism either way).

When called:

  1. ``data`` is stored on ``session.loop_state["__early_exit__"]`` so the
     ReAct loop terminates at its next checkpoint.
  2. A :class:`StopEvent` is published on the bus, observable by anyone
     subscribing for logging / debugging / replay.

Construct with ``next_session_id`` only when the tool's binding is
"hand the baton to that specific session" (used by ``PipelineRuntime``);
leave empty for ordinary "this is my final answer" use.
"""

from __future__ import annotations

from typing import Any


class EndTool:
    """The agent's "I'm done" tool.

    For a single-agent ReactAgent: ``data`` is the final answer to the user.
    For a pipeline middle stage: ``data`` is the payload for the next agent.

    The mechanism is the same either way — what differs is who reads ``data``
    next. ``next_session_id`` is informational (used in StopEvent.reason for
    traceability) and does not affect routing.
    """

    type = "function"
    name = "end"
    description = (
        "Call this when you have finished your task. The `data` argument is "
        "your final delivery — it's everything the caller (the user, or in a "
        "pipeline the next agent) needs. After this call your loop terminates "
        "immediately, so put the FULL answer in `data`. Do NOT also write the "
        "answer in your message content — content is discarded once `end` is "
        "called."
    )
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": (
                    "Your final, self-contained answer (or handoff payload). "
                    "The recipient does not see your internal reasoning or "
                    "tool calls — be explicit and complete."
                ),
            }
        },
        "required": ["data"],
    }

    def __init__(self, next_session_id: str = ""):
        self._next_session_id = next_session_id

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
                    reason=(
                        f"handoff to '{self._next_session_id}'"
                        if self._next_session_id
                        else "task complete"
                    ),
                    data=data,
                )
            )
        return (
            f"Handoff scheduled. Next agent: {self._next_session_id}"
            if self._next_session_id
            else "Task marked complete."
        )
