"""评论能力契约, 定义用户在对话或消息下发表评论的调用约定

权限规则由实现内部执行:
- 创建评论需要已登录, 并且有权查看评论目标所在的对话
- 删除评论需要管理员权限

当前用户一律以 `UserView` 传入, 不使用带密码散列的领域模型.

契约只声明软删除. 评论需要保留审计痕迹, 不提供物理删除.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.enums import CommentTarget
from core.models import Comment
from core.types import CommentId
from modules.interfaces.users_intf import UserView


@dataclass
class CommentSubmission:
    """创建一条评论的输入

    `target_source_id` 的含义由 `target_type` 决定:
    对话评论指向 Conversation.source_id, 消息评论指向 Message.source_id.
    当前 `CommentService.create` 仍然接收拆开的参数, 这是留给 Web 层
    统一收口的输入形状, 待请求模型接入后再改造成整体传入.
    """

    target_type: CommentTarget
    target_source_id: str
    content: str
    nickname: str = "anonymous"


@runtime_checkable
class CommentServiceContract(Protocol):
    """评论能力契约

    具体实现的构造依赖为: 评论仓储契约和查询能力契约.

    实现会通过查询能力解析评论目标的归属, 而不是直接访问消息仓储,
    因此本契约不暴露任何持久化对象.

    刻意不提供修改评论的调用: 评论一经发表即作为他人的阅读上下文存在,
    修改会导致上下文失真, 需要更正时用删除加重新发表代替.
    """

    def create(
        self,
        user: UserView | None,
        target_type: CommentTarget,
        target_source_id: str,
        content: str,
        nickname: str = "anonymous",
    ) -> Comment:
        """在对话或消息下创建一条评论

        内容为空时抛出 ValidationError, 目标类型非法时抛出 ValidationError,
        评论目标不存在时抛出 NotFoundError, 权限不足时抛出 PermissionDeniedError
        """
        ...

    def list_by_conversation(self, conversation_source_id: str) -> list[Comment]:
        """查询直接挂在某个对话下的有效评论

        只返回直接挂在对话下的评论, 不包含该对话所属消息的评论,
        因为消息级评论在库内不记录所属对话. 需要覆盖消息评论时使用
        `list_by_conversation_including_messages`.
        """
        ...

    def list_by_conversation_including_messages(
        self,
        conversation_source_id: str,
    ) -> list[Comment]:
        """查询某个对话下的全部有效评论, 含该对话所属消息的评论

        对话评论与消息评论合并后按时间线排序, 已删除的评论不返回.
        这是"查看该对话下所有讨论"的整体视图, 不需要调用方逐个消息拼接.
        """
        ...

    def list_by_message(self, message_source_id: str) -> list[Comment]:
        """查询某条消息下的有效评论, 已删除的评论不返回"""
        ...

    def delete(self, user: UserView | None, comment_id: CommentId) -> None:
        """软删除一条评论, 需要管理员权限"""
        ...


__all__ = [
    "CommentServiceContract",
    "CommentSubmission",
]