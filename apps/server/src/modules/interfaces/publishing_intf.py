"""发布能力契约, 定义面向展示场景的读取, 筛选和发布状态控制

本模块同时声明展示场景的输出形状. 展示输出与查询输出的区别在于:
展示输出必须剥离思考内容, 原始备份位置和导入批次等内部字段,
只保留前端能够安全使用的部分.

展示输出按"当前链"展开: 一个对话在库内可以有多条分支, 但展示场景只呈现
当前链, 每条消息的 position 在所属分支内从 1 开始编号, 把多条分支并成一个
平铺列表会产生重复序号和互相冲突的内容.

`list_for_view` 返回 `PublishedConversationSummary`, 它是展示场景的列表项,
比 `Conversation` 少了备份组织和导入批次字段.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from core.enums import MessageRole
from core.models import Conversation
from core.pagination import Page, PageResult
from modules.interfaces.users_intf import UserView


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


@dataclass
class PublishedConversationSummary:
    """展示场景下的对话列表项

    列表场景不需要消息内容, 因此只保留标题和时间. 与
    `PublishedConversationView` 一样剥离备份组织和导入批次字段,
    避免列表接口成为泄露这些字段的旁路
    """

    source_id: str
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@runtime_checkable
class PublicationServiceContract(Protocol):
    """发布能力契约

    具体实现的构造依赖为: 查询能力契约和对话仓储契约.
    本契约的每个方法都接收当前用户, 由实现内部完成权限判断,
    调用方不需要也不应该自己判断权限.
    """

    def list_for_view(
        self,
        user: UserView | None,
        page: Page,
    ) -> PageResult[PublishedConversationSummary]:
        """按用户权限返回一页可查看的对话列表

        管理员看到全部对话, 其他用户只看到已发布的对话.
        返回值已剥离备份组织和导入批次字段
        """
        ...

    def get_conversation_for_view(
        self,
        user: UserView | None,
        conversation_source_id: str,
    ) -> PublishedConversationView | None:
        """按用户权限获取一个对话的展示详情

        无权查看时返回 None, 对话不存在时也返回 None. 两种情况统一返回
        None, 是为了让调用方无法通过返回值区分"对话不存在"和"存在但未发布",
        否则未发布的对话标题会被枚举出来.
        """
        ...

    def list_messages_for_view(
        self,
        user: UserView | None,
        conversation_source_id: str,
        branch_source_id: str | None,
        page: Page,
    ) -> PageResult[PublishedMessageView] | None:
        """按用户权限分页获取一个对话下某个分支的消息

        无权查看或对话不存在时返回 None, 与 `get_conversation_for_view` 的
        约定一致, 调用方无法借此枚举未发布的对话.

        `branch_source_id` 为 None 时使用当前链. 指定了分支但该分支不属于
        这个对话时同样返回 None, 而不是返回空列表: 空列表会让调用方以为
        "这个分支没有消息", 而实际原因是分支根本不属于这个对话.
        """
        ...

    def publish(self, user: UserView | None, conversation_source_id: str) -> Conversation:
        """发布一个对话, 需要管理员权限

        对话不存在时抛出 NotFoundError, 权限不足时抛出 PermissionDeniedError
        """
        ...

    def unpublish(self, user: UserView | None, conversation_source_id: str) -> Conversation:
        """隐藏一个对话, 需要管理员权限

        对话不存在时抛出 NotFoundError, 权限不足时抛出 PermissionDeniedError
        """
        ...


__all__ = [
    "PublicationServiceContract",
    "PublishedConversationSummary",
    "PublishedConversationView",
    "PublishedMessageView",
]