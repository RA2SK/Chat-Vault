from core.exceptions import NotFoundError
from core.messages import MessageKey
from core.models import Attachment, Branch, Conversation, Message
from core.pagination import Page, PageResult
from modules.interfaces.publishing_intf import (
    PublishedConversationSummary,
    PublishedConversationView,
    PublishedMessageView,
)
from modules.interfaces.querying_intf import ConversationDetail
from modules.interfaces.users_intf import UserView
from modules.repositories.conversations import ConversationRepository
from modules.repositories.database import transaction
from modules.services.querying import QueryService
from modules.services.users import is_admin, require_admin


def to_published_message_view(
    message: Message,
    attachments: list[Attachment],
) -> PublishedMessageView:
    """把一条消息转换成展示视图, 只保留前端可以安全使用的字段"""

    return PublishedMessageView(
        source_id=message.source_id,
        role=message.role,
        content=message.content,
        position=message.position,
        model=message.model,
        timestamp=message.timestamp,
        edited_at=message.edited_at,
        attachments=[attachment.source_ref for attachment in attachments],
    )


def to_published_conversation_view(
    detail: ConversationDetail,
) -> PublishedConversationView:
    """把一个对话详情转换成展示视图

    只展开当前链: 展示场景呈现的是对话的最终形态, 历史分支属于内容图的
    内部结构. 每条消息的 position 在所属分支内编号, 合并多条分支会产生
    重复序号和互相冲突的内容, 因此不合并.
    """

    current_branch = _current_branch(detail)
    messages: list[PublishedMessageView] = []

    if current_branch is not None:
        for message in detail.messages.get(current_branch.source_id, []):
            messages.append(
                to_published_message_view(
                    message,
                    detail.attachments.get(message.source_id, []),
                ),
            )

    return PublishedConversationView(
        source_id=detail.conversation.source_id,
        title=detail.conversation.title,
        created_at=detail.conversation.created_at,
        updated_at=detail.conversation.updated_at,
        messages=messages,
    )


def to_published_conversation_summary(
    conversation: Conversation,
) -> PublishedConversationSummary:
    """把一个对话转换成展示列表项"""

    return PublishedConversationSummary(
        source_id=conversation.source_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _current_branch(detail: ConversationDetail) -> Branch | None:
    """取出展示使用的当前链

    优先取标记为 is_current 的分支. 没有任何分支被标记时取消息最多的一条,
    避免对话因为元数据缺失而显示为空.
    """

    for branch in detail.branches:
        if branch.is_current:
            return branch

    if not detail.branches:
        return None

    return max(
        detail.branches,
        key=lambda branch: len(detail.messages.get(branch.source_id, [])),
    )


def _current_branch_from(branches: list[Branch]) -> Branch | None:
    """从分支列表里取出展示使用的当前链, 不依赖已加载的消息

    与 `_current_branch` 的区别是拿不到"消息最多的一条"这个判据, 因为分页
    展示场景下消息是按页取的. 因此退化为取第一条, 而不是为了凑出判据去
    加载全部消息 —— 那会让分页失去意义.
    """

    for branch in branches:
        if branch.is_current:
            return branch

    if not branches:
        return None

    return branches[0]


def can_view_conversation(user: UserView | None, conversation: Conversation) -> bool:
    """判断用户是否可以查看指定对话"""

    return (
        conversation.is_published
        or is_admin(user)
    )


def can_publish_conversation(user: UserView | None, conversation: Conversation) -> bool:
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


    def list_for_view(
        self,
        user: UserView | None,
        page: Page,
    ) -> PageResult[PublishedConversationSummary]:
        """按用户权限返回一页可查看的对话列表"""

        if is_admin(user):
            result = self.query_service.list_conversations(page)
        else:
            result = self.query_service.list_published_conversations(page)

        return PageResult(
            items=[
                to_published_conversation_summary(conversation)
                for conversation in result.items
            ],
            has_more=result.has_more,
        )


    def get_conversation_for_view(
        self,
        user: UserView | None,
        conversation_source_id: str,
    ) -> PublishedConversationView | None:
        """按用户权限获取一个对话的展示详情

        无权查看时返回 None, 与对话不存在时的返回值一致, 调用方无法借此
        枚举未发布的对话.
        """

        detail = self.query_service.get_conversation_detail(conversation_source_id)
        if detail is None:
            return None

        if not can_view_conversation(user, detail.conversation):
            return None

        return to_published_conversation_view(detail)


    def list_messages_for_view(
        self,
        user: UserView | None,
        conversation_source_id: str,
        branch_source_id: str | None,
        page: Page,
    ) -> PageResult[PublishedMessageView] | None:
        """按用户权限分页获取一个对话下某个分支的消息"""

        conversation = self.query_service.get_conversation(conversation_source_id)
        if conversation is None:
            return None

        if not can_view_conversation(user, conversation):
            return None

        branches = self.query_service.list_branches(conversation_source_id)

        if branch_source_id is None:
            branch = _current_branch_from(branches)
        else:
            branch = next(
                (
                    candidate
                    for candidate in branches
                    if candidate.source_id == branch_source_id
                ),
                None,
            )

        if branch is None:
            return None

        result = self.query_service.list_messages(branch.source_id, page)
        attachments = self.query_service.list_attachments_for_messages(
            [message.source_id for message in result.items],
        )

        return PageResult(
            items=[
                to_published_message_view(
                    message,
                    attachments.get(message.source_id, []),
                )
                for message in result.items
            ],
            has_more=result.has_more,
        )


    def publish(self, user: UserView | None, conversation_source_id: str) -> Conversation:
        """发布一个对话"""

        require_admin(user)
        return self._set_published(conversation_source_id, True)


    def unpublish(self, user: UserView | None, conversation_source_id: str) -> Conversation:
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
            raise NotFoundError(
                MessageKey.CONVERSATION_NOT_FOUND,
                conversation_source_id=conversation_source_id,
            )

        # 赋值放在事务内: 若 update() 抛异常, 事务回滚, 数据库状态不变,
        # 此时内存中的 conversation 也必须保持原状, 否则本方法返回的对象
        # 会声称 "已发布" 而库里并没有发布.
        with transaction(self.conversation_repository.connection):
            conversation.is_published = is_published
            self.conversation_repository.update(conversation)

        return conversation
