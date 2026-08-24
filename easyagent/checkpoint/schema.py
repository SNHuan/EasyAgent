from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticSerializationError

if TYPE_CHECKING:
    from easyagent.agent.session import AgentSession


class UnsupportedCheckpointVersionError(ValueError):
    """Raised when a checkpoint uses an unsupported schema version."""

    def __init__(self, version: object) -> None:
        self.version = version
        super().__init__(
            f"Unsupported checkpoint schema version: {version!r}"
        )


class InvalidCheckpointStateError(ValueError):
    """Raised when checkpoint state cannot be decoded into an AgentSession."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(
            f"Checkpoint '{session_id}' contains invalid restorable state"
        )


class AgentCheckpoint(BaseModel):
    """Serializable snapshot of agent session state."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        ser_json_inf_nan="constants",
    )

    schema_version: Literal[1] = 1
    session_id: str
    agent_identity: str
    agent_name: str
    agent_type: str
    status: str
    iteration_count: int
    final_output: str | None = None
    messages: tuple[dict[str, Any], ...] = ()
    loop_steps: tuple[dict[str, Any], ...] = ()
    enabled_tools: tuple[str, ...] = ()
    loaded_skills: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    loop_state: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def capture(cls, session: AgentSession) -> AgentCheckpoint:
        agent = session.agent
        checkpoint = cls(
            session_id=session.session_id,
            agent_identity=(
                getattr(agent, "checkpoint_identity", "")
                or (
                    f"{type(agent).__module__}.{type(agent).__qualname__}"
                    if agent is not None
                    else ""
                )
            ),
            agent_name=getattr(agent, "name", ""),
            agent_type=type(agent).__name__ if agent is not None else "",
            status=session.status.value,
            iteration_count=session.iteration_count,
            final_output=session.final_output,
            messages=tuple(
                message.model_dump(exclude_none=True)
                for message in session.get_all_messages()
            ),
            loop_steps=tuple(
                {
                    "status": step.status.value,
                    "output": step.output,
                }
                for step in session.loop_steps
            ),
            enabled_tools=tuple(session.enabled_tools),
            loaded_skills=tuple(session.loaded_skills),
            metadata=dict(session.metadata),
            loop_state=dict(session.loop_state),
        )
        return cls.from_dict(checkpoint.to_dict())

    def to_dict(self) -> dict[str, Any]:
        try:
            payload = self.model_dump(mode="json")
            json.dumps(payload, allow_nan=False)
            return payload
        except (PydanticSerializationError, TypeError, ValueError) as exc:
            raise TypeError(
                "Checkpoint contains non-JSON-serializable state"
            ) from exc

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentCheckpoint:
        version = payload.get("schema_version")
        if type(version) is not int or version != 1:
            raise UnsupportedCheckpointVersionError(version)
        return cls.model_validate(payload)
