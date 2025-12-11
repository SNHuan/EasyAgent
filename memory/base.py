from abc import ABC, abstractmethod

from model.schema import Message


class BaseMemory(ABC):
    """Memory 抽象基类：管理对话历史"""

    @abstractmethod
    def add(self, message: Message) -> None:
        """添加消息"""
        ...

    @abstractmethod
    def get_messages(self) -> list[Message]:
        """获取当前有效的消息列表"""
        ...

    @abstractmethod
    def clear(self) -> None:
        """清空历史"""
        ...

    @property
    @abstractmethod
    def token_count(self) -> int:
        """当前总 token 数"""
        ...

