# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from core.models import Conversation, User
from modules.interfaces.querying_intf import ConversationDetail
from modules.repositories.conversations import ConversationRepository
from modules.services.querying import QueryService
from modules.services.users import is_admin, require_admin


def can_view_conversation(user: User | None, conversation: Conversation) -> bool:
    """判断用户是否可以查看指定对话"""

    return (
        conversation.is_published
        or is_admin(user)
    )


def can_publish_conversation(user: User | None, conversation: Conversation) -> bool:
    """判断用户是否可以发布或隐藏指定对话"""

    return is_admin(user)


class PublishingService:
    """读取并筛选可发布内容, 控制对话的发布状态"""

    def __init__(
        self,
        query_service: QueryService,
        conversation_repository: ConversationRepository,
    ):
        self.query_service = query_service
        self.conversation_repository = conversation_repository


    def list_for_view(self, user: User | None) -> list[Conversation]:
        """按用户权限返回可查看的对话列表"""

        if is_admin(user):
            return self.query_service.list_conversations()

        return self.query_service.list_published_conversations()


    def get_conversation_for_view(
        self,
        user: User | None,
        conversation_source_id: str,
    ) -> ConversationDetail | None:
        """按用户权限获取一个对话的完整详情"""

        detail = self.query_service.get_conversation_detail(conversation_source_id)
        if detail is None:
            return None

        if not can_view_conversation(user, detail.conversation):
            raise PermissionError("无权查看该对话")

        return detail


    def publish(self, user: User | None, conversation_source_id: str) -> Conversation:
        """发布一个对话"""

        require_admin(user)
        return self._set_published(conversation_source_id, True)


    def unpublish(self, user: User | None, conversation_source_id: str) -> Conversation:
        """隐藏一个对话"""

        require_admin(user)
        return self._set_published(conversation_source_id, False)


    def _set_published(
        self,
        conversation_source_id: str,
        is_published: bool,
    ) -> Conversation:
        """更新对话的发布状态"""

        conversation = self.conversation_repository.get_by_source_id(
            conversation_source_id,
        )
        if conversation is None:
            raise LookupError(f"对话 {conversation_source_id} 不存在")

        conversation.is_published = is_published
        self.conversation_repository.update(conversation)
        return conversation
