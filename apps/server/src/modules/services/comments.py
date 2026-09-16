from datetime import datetime, timezone

from core.enums import CommentTarget
from core.exceptions import (
    NotAuthenticatedError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from core.messages import MessageKey
from core.models import Comment, Conversation
from core.pagination import Page, PageResult
from core.types import CommentId
from modules.interfaces.comments_intf import CommentSubmission
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
        submission: CommentSubmission,
    ) -> Comment:
        """在对话或消息下创建一条评论"""

        target_type = submission.target_type
        target_source_id = submission.target_source_id

        if not submission.content:
            raise ValidationError(MessageKey.COMMENT_CONTENT_EMPTY)

        conversation_source_id: str | None = None
        message_source_id: str | None = None

        if target_type == CommentTarget.CONVERSATION:
            conversation = self.query_service.get_conversation(target_source_id)
            if conversation is None:
                raise NotFoundError(
                    MessageKey.CONVERSATION_NOT_FOUND,
                    conversation_source_id=target_source_id,
                )
            conversation_source_id = target_source_id
            target = conversation
        elif target_type == CommentTarget.MESSAGE:
            message = self.query_service.get_message(target_source_id)
            if message is None:
                raise NotFoundError(
                    MessageKey.MESSAGE_NOT_FOUND,
                    message_source_id=target_source_id,
                )
            message_source_id = target_source_id
            owner_conversation_source_id = (
                self.query_service.get_message_conversation_source_id(target_source_id)
            )
            if owner_conversation_source_id is None:
                raise NotFoundError(
                    MessageKey.MESSAGE_OWNER_CONVERSATION_NOT_FOUND,
                    message_source_id=target_source_id,
                )
            target = self.query_service.get_conversation(owner_conversation_source_id)
            if target is None:
                raise NotFoundError(
                    MessageKey.MESSAGE_OWNER_CONVERSATION_NOT_FOUND,
                    message_source_id=target_source_id,
                )
        else:
            raise ValidationError(MessageKey.COMMENT_TARGET_INVALID)

        if not can_create_comment(user, target):
            raise PermissionDeniedError(MessageKey.COMMENT_CREATE_FORBIDDEN)

        # can_create_comment 已经要求 user 非空, 这里再断言一次是为了让类型
        # 收窄对类型检查器可见. 用显式检查而不是 assert: assert 在 -O 下会被
        # 剥掉, 生产环境里就只剩一个静默的 None 解引用.
        if user is None:
            raise NotAuthenticatedError(MessageKey.AUTHENTICATION_REQUIRED)

        comment = Comment(
            target_type=target_type,
            content=submission.content,
            created_at=datetime.now(timezone.utc),
            created_by=user.id,
            nickname=submission.nickname,
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

        当前没有生产调用方: 展示侧一律走 `list_by_conversation_including_messages`,
        因为前端要展示的是"这个对话下的所有讨论". 保留本方法是为了让"只要
        对话级评论"这个语义有明确的入口, 而不是让调用方去猜合并版本能不能
        过滤. 新增调用方前请先确认确实不需要消息级评论.
        """

        return self.comment_repository.list_by_conversation(conversation_source_id)


    def list_by_conversation_including_messages(
        self,
        conversation_source_id: str,
        page: Page,
    ) -> PageResult[Comment]:
        """查询某个对话下的全部有效评论, 含该对话所属消息的评论

        对话评论与消息评论合并后按时间线排序, 供"查看该对话下所有讨论"
        这类整体视图使用.
        """

        return self.comment_repository.list_by_conversation_including_messages(
            conversation_source_id,
            limit=page.limit,
            offset=page.offset,
        )


    def list_by_message(self, message_source_id: str) -> list[Comment]:
        """查询某条消息下的有效评论

        当前没有生产调用方: 展示侧走 `list_by_conversation_including_messages`
        一次取全. 保留本方法是为了让"单条消息的评论"这个语义有明确入口,
        将来做消息详情页时会用到.
        """

        return self.comment_repository.list_by_message(message_source_id)


    def delete(self, user: UserView | None, comment_id: CommentId) -> None:
        """软删除一条评论"""

        require_admin(user)

        with transaction(self.comment_repository.connection):
            deleted = self.comment_repository.soft_delete(comment_id)

        if not deleted:
            raise NotFoundError(
                MessageKey.COMMENT_NOT_FOUND,
                comment_id=comment_id,
            )
