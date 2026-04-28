"""Think tool — a scratch pad for the agent's reasoning.

A ``ReactAgent`` registers this by default. Calling ``think`` produces no
side effects; the value of ``thought`` lands in the tool-call history so
the model can re-read its own reasoning on the next turn, and observers
get the usual ``ToolCalledEvent`` / ``ToolResultEvent`` pair.

It is most useful as a "pause and reflect" step — especially right before
``end`` — to verify the answer covers the user's request.
"""

from __future__ import annotations

from typing import Any


class ThinkTool:
    """The agent's "let me think" tool.

    ``thought`` is free-form reasoning, planning, or self-check. Nothing
    external happens; the value is simply echoed back so it stays in the
    conversation as a tool result the model can refer to.
    """

    type = "function"
    name = "think"
    description = (
        "Use this to pause and reason before acting. The `thought` argument "
        "is your private reflection — plan, self-check, or weigh options. "
        "It has no side effects. verify your answer fully addresses the request, then conclude."
    )
    parameters = {
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": (
                    "Your reasoning, plan, or self-check. Be concrete: "
                    "what have you done, what is left, does the answer "
                    "cover everything the caller asked for?"
                ),
            }
        },
        "required": ["thought"],
    }

    def init(self) -> None:
        pass

    async def execute(
        self,
        thought: str,
        *,
        session: Any | None = None,
        **kwargs: Any,
    ) -> str:
        return "Thought recorded."
