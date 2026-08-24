from typing import Any

from easyagent.model.schema import Message


def serialize_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {}
        for key, value in message.items():
            item[key] = (
                truncate_message_content(value)
                if key == "content"
                else value
            )
        serialized.append(item)
    return serialized


def truncate_message_content(content: Any) -> Any:
    if isinstance(content, str):
        return (
            content
            if len(content) <= 8_000
            else f"{content[:8_000]}... [truncated]"
        )
    if isinstance(content, list):
        return [truncate_message_content(item) for item in content]
    if isinstance(content, dict):
        return {
            str(key): truncate_message_content(value)
            for key, value in content.items()
        }
    return content


def serialize_session_messages(
    messages: list[Message],
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for message in messages:
        data = message.model_dump(exclude_none=True)
        if "content" in data:
            data["content"] = truncate_message_content(data["content"])
        serialized.append(data)
    return serialized


def serialize_tool_calls(response: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(response, "tool_calls", None) or []
    serialized: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if hasattr(tool_call, "model_dump"):
            serialized.append(tool_call.model_dump())
        elif isinstance(tool_call, dict):
            serialized.append(tool_call)
    return serialized
