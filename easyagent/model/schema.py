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
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: Any) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: Any) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(
        cls,
        content: Any,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls, reasoning_content=reasoning_content)

    @classmethod
    def from_response(cls, response: "LLMResponse") -> "Message":
        """从 LLMResponse 创建 assistant Message，保留完整信息。"""
        return cls(
            role="assistant",
            content=response.content,
            reasoning_content=response.reasoning_content,
            tool_calls=[tc.model_dump() for tc in response.tool_calls] if response.tool_calls else None,
        )

    @classmethod
    def tool(cls, content: Any, tool_call_id: str) -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id)

    def text(self) -> str:
        return content_to_text(self.content)

    def to_api_dict(self) -> dict[str, Any]:
        """渲染为 LLM API 所需的 dict 格式，将 reasoning_content 合并到 content。"""
        content = self.content
        # 对于 assistant 消息，将 reasoning_content 合并到 content
        if self.role == "assistant" and self.reasoning_content:
            content = f"<think>{self.reasoning_content}</think>\n{content}"
        
        result: dict[str, Any] = {"role": self.role, "content": content}
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


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

