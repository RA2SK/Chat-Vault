"""发布能力契约, 定义面向展示场景的读取, 筛选和发布状态控制

本模块同时声明展示场景的输出形状. 展示输出与查询输出的区别在于:
展示输出必须剥离思考内容, 原始备份位置和导入批次等内部字段,
只保留前端能够安全使用的部分.

`PublishedConversationView` 和 `PublishedMessageView` 是展示输出的目标形状.
当前 `PublishingService.get_conversation_for_view` 仍然直接返回
`ConversationDetail`, 尚未做字段剥离, 因此契约暂时按现状声明返回类型,
待展示整理逻辑实现后再收窄为视图类型.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from core.enums import MessageRole
from core.models import Conversation, User
from modules.interfaces.querying_intf import ConversationDetail


@dataclass
class PublishedMessageView:
    """展示场景下的一条消息

    刻意不包含 thinking, 因为思考内容默认不展示;
    也不包含 edited_by, 因为编辑者身份属于管理侧信息
    """

    source_id: str
    role: MessageRole
    content: str
    position: int
    model: str | None = None
    timestamp: datetime | None = None
    edited_at: datetime | None = None
    attachments: list[str] = field(default_factory=list)


@dataclass
class PublishedConversationView:
    """展示场景下的一个对话

    刻意不包含 source_archive, source_entry 和 import_batch_id,
    这些字段暴露了原始备份的组织方式, 只对管理侧有意义
    """

    source_id: str
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: list[PublishedMessageView] = field(default_factory=list)


@runtime_checkable
class PublicationServiceContract(Protocol):
    """发布能力契约

    具体实现的构造依赖为: 查询能力契约和对话仓储契约.
    本契约的每个方法都接收当前用户, 由实现内部完成权限判断,
    调用方不需要也不应该自己判断权限.
    """

    def list_for_view(self, user: User | None) -> list[Conversation]:
        """按用户权限返回可查看的对话列表

        管理员看到全部对话, 其他用户只看到已发布的对话
        """
        ...

    def get_conversation_for_view(
        self,
        user: User | None,
        conversation_source_id: str,
    ) -> ConversationDetail | None:
        """按用户权限获取一个对话的完整详情

        对话不存在时返回 None, 存在但无权查看时抛出 PermissionError
        """
        ...

    def publish(self, user: User | None, conversation_source_id: str) -> Conversation:
        """发布一个对话, 需要管理员权限

        对话不存在时抛出 LookupError, 权限不足时抛出 PermissionError
        """
        ...

    def unpublish(self, user: User | None, conversation_source_id: str) -> Conversation:
        """隐藏一个对话, 需要管理员权限

        对话不存在时抛出 LookupError, 权限不足时抛出 PermissionError
        """
        ...


__all__ = [
    "PublicationServiceContract",
    "PublishedConversationView",
    "PublishedMessageView",
]