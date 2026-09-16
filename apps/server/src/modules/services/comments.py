# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from datetime import datetime, timezone

from core.enums import CommentTarget
from core.models import Comment, Conversation
from core.types import CommentId
from modules.interfaces.users_intf import UserView
from modules.repositories.comments import CommentRepository
from modules.repositories.database import transaction
from modules.services.publishing import can_view_conversation
from modules.services.querying import QueryService
from modules.services.users import is_admin, is_authenticated, require_admin


def can_create_comment(user: UserView | None, conversation: Conversation) -> bool:
    """判断用户是否可以在指定对话下创建评论"""

    return (
        is_authenticated(user)
        and can_view_conversation(user, conversation)
    )


def can_delete_comment(user: UserView | None, comment: Comment) -> bool:
    """判断用户是否可以删除评论"""

    return is_admin(user)


class CommentService:
    """处理用户评论的创建, 读取和删除"""

    def __init__(
        self,
        comment_repository: CommentRepository,
        query_service: QueryService,
    ):
        self.comment_repository = comment_repository
        self.query_service = query_service


    def create(
        self,
            user: UserView | None,
        target_type: CommentTarget,
        target_source_id: str,
        content: str,
        nickname: str = "anonymous",
    ) -> Comment:
        """在对话或消息下创建一条评论"""

        if not content:
            raise ValueError("评论内容不能为空")

        conversation_source_id: str | None = None
        message_source_id: str | None = None

        if target_type == CommentTarget.CONVERSATION:
            conversation = self.query_service.get_conversation(target_source_id)
            if conversation is None:
                raise LookupError(f"对话 {target_source_id} 不存在")
            conversation_source_id = target_source_id
            target = conversation
        elif target_type == CommentTarget.MESSAGE:
            message = self.query_service.get_message(target_source_id)
            if message is None:
                raise LookupError(f"消息 {target_source_id} 不存在")
            message_source_id = target_source_id
            owner_conversation_source_id = (
                self.query_service.get_message_conversation_source_id(target_source_id)
            )
            if owner_conversation_source_id is None:
                raise LookupError(f"消息 {target_source_id} 所属对话不存在")
            target = self.query_service.get_conversation(owner_conversation_source_id)
            if target is None:
                raise LookupError(f"消息 {target_source_id} 所属对话不存在")
        else:
            raise ValueError("target_type 必须是 conversation 或 message")

        if not can_create_comment(user, target):
            raise PermissionError("无权在该目标下创建评论")

        assert user is not None
        comment = Comment(
            target_type=target_type,
            content=content,
            created_at=datetime.now(timezone.utc),
            created_by=user.id,
            nickname=nickname,
            conversation_source_id=conversation_source_id,
            message_source_id=message_source_id,
        )

        with transaction(self.comment_repository.connection):
            self.comment_repository.create(comment)

        return comment


    def list_by_conversation(self, conversation_source_id: str) -> list[Comment]:
        """查询直接挂在某个对话下的有效评论

        只返回直接挂在对话下的评论, 不包含该对话所属消息的评论.
        需要覆盖消息评论时使用 `list_by_conversation_including_messages`.
        """

        return self.comment_repository.list_by_conversation(conversation_source_id)


    def list_by_conversation_including_messages(
        self,
        conversation_source_id: str,
    ) -> list[Comment]:
        """查询某个对话下的全部有效评论, 含该对话所属消息的评论

        对话评论与消息评论合并后按时间线排序, 供"查看该对话下所有讨论"
        这类整体视图使用.
        """

        return self.comment_repository.list_by_conversation_including_messages(
            conversation_source_id,
        )


    def list_by_message(self, message_source_id: str) -> list[Comment]:
        """查询某条消息下的有效评论"""

        return self.comment_repository.list_by_message(message_source_id)


    def delete(self, user: UserView | None, comment_id: CommentId) -> None:
        """软删除一条评论"""

        require_admin(user)

        with transaction(self.comment_repository.connection):
            self.comment_repository.soft_delete(comment_id)
