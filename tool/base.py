from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """Tool 鸭子类型协议"""

    name: str
    type: str  # "function"
    description: str

    def init(self) -> None:
        ...

    def execute(self, **kwargs: Any) -> str:
        ...

