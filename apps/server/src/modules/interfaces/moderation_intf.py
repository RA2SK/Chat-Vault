"""管理能力契约, 定义管理员对消息的标记管理

消息编辑和编辑历史尚未实现, 因此本模块只声明标记相关的调用.
`MessageEditRequest` 先按目标形状定义, 供后续实现编辑能力时使用.

权限规则由实现内部执行, 不在契约中表达:
- 添加和删除标记需要管理员权限
- 编辑消息需要管理员权限

当前用户一律以 `UserView` 传入, 不使用带密码散列的领域模型.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.enums import MarkType
from core.models import AdminMark
from core.pagination import Page, PageResult
from core.types import AdminMarkId
from modules.interfaces.users_intf import UserView


@dataclass
class MessageEditRequest:
    """一次消息编辑的输入

    `reason` 用于记录编辑原因, 会写入编辑历史
    """

    content: str
    thinking: str = ""
    reason: str | None = None


@runtime_checkable
class ModerationServiceContract(Protocol):
    """管理能力契约

    具体实现的构造依赖为: 管理员标记仓储契约和消息仓储契约.
    """

    def add_mark(
        self,
        user: UserView | None,
        message_source_id: str,
        mark_type: MarkType,
    ) -> AdminMark:
        """为消息添加一个管理员标记

        消息不存在时抛出 NotFoundError, 权限不足时抛出 PermissionDeniedError
        """
        ...

    def remove_mark(self, user: UserView | None, mark_id: AdminMarkId) -> None:
        """软删除一个管理员标记, 需要管理员权限"""
        ...

    def list_marks(
        self,
        user: UserView | None,
        message_source_id: str,
        page: Page,
    ) -> PageResult[AdminMark]:
        """分页查询某条消息下的有效管理员标记, 已删除的标记不返回, 需要管理员权限"""
        ...


# 待实现, 实现后加入本契约:
# - edit_message(user, message_source_id, request) -> Message
# - restore_message(user, message_source_id, revision_no) -> Message
# - list_revisions(message_source_id) -> list[MessageRevision]
# MessageRevision 目前只有模型定义, schema.sql 尚未持久化该表.


__all__ = [
    "MessageEditRequest",
    "ModerationServiceContract",
]