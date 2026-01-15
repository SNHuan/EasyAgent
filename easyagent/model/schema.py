from typing import Any, Literal

from pydantic import BaseModel


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "text":
                    parts.append(str(item.get("text", "")))
                    continue
                if item_type == "image_url":
                    url = item.get("image_url", {}).get("url")
                    parts.append(f"[image:{url}]" if url else "[image]")
                    continue
                if "text" in item:
                    parts.append(str(item.get("text", "")))
                    continue
                parts.append(str(item))
            else:
                parts.append(str(item))
        return " ".join(p for p in parts if p)
    if isinstance(content, dict):
        if "text" in content:
            text = str(content.get("text", ""))
            images = content.get("images") or []
            image_text = " ".join(f"[image:{img}]" for img in images) if images else ""
            return " ".join(p for p in (text, image_text) if p)
    return str(content)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Any
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: Any) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: Any) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: Any, tool_calls: list[dict[str, Any]] | None = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, content: Any, tool_call_id: str) -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id)

    def text(self) -> str:
        return content_to_text(self.content)


class ToolCall(BaseModel):
    id: str
    type: str
    name: str
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    content: str
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: dict[str, Any] | None = None

