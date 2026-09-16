from datetime import datetime, timezone

from core.enums import MarkType
from core.exceptions import NotAuthenticatedError, NotFoundError
from core.messages import MessageKey
from core.models import AdminMark, Message
from core.pagination import Page, PageResult
from core.types import AdminMarkId
from modules.interfaces.users_intf import UserView
from modules.repositories.database import transaction
from modules.repositories.messages import MessageRepository
from modules.repositories.moderation import AdminMarkRepository
from modules.services.users import is_admin, require_admin


def can_edit_message(user: UserView | None, message: Message) -> bool:
    """判断用户是否可以编辑指定消息"""

    return is_admin(user)


def can_create_admin_mark(user: UserView | None, message: Message) -> bool:
    """判断用户是否可以为消息添加管理员标记"""

    return is_admin(user)


def can_delete_admin_mark(user: UserView | None, mark: AdminMark) -> bool:
    """判断用户是否可以删除管理员标记"""

    return is_admin(user)


class ModerationService:
    """处理管理员对消息的标记管理"""

    def __init__(
        self,
        admin_mark_repository: AdminMarkRepository,
        message_repository: MessageRepository,
    ):
        self.admin_mark_repository = admin_mark_repository
        self.message_repository = message_repository


    def add_mark(
        self,
        user: UserView | None,
        message_source_id: str,
        mark_type: MarkType,
    ) -> AdminMark:
        """为消息添加一个管理员标记"""

        require_admin(user)

        message = self.message_repository.get_by_source_id(message_source_id)
        if message is None:
            raise NotFoundError(
                MessageKey.MESSAGE_NOT_FOUND,
                message_source_id=message_source_id,
            )

        if user is None:
            raise NotAuthenticatedError(MessageKey.AUTHENTICATION_REQUIRED)

        mark = AdminMark(
            message_source_id=message_source_id,
            mark_type=mark_type,
            created_at=datetime.now(timezone.utc),
            created_by=user.id,
        )

        with transaction(self.admin_mark_repository.connection):
            self.admin_mark_repository.create(mark)

        return mark


    def remove_mark(self, user: UserView | None, mark_id: AdminMarkId) -> None:
        """软删除一个管理员标记"""

        require_admin(user)

        with transaction(self.admin_mark_repository.connection):
            deleted = self.admin_mark_repository.soft_delete(mark_id)

        if not deleted:
            raise NotFoundError(
                MessageKey.MARK_NOT_FOUND,
                mark_id=mark_id,
            )


    def list_marks(
        self,
        user: UserView | None,
        message_source_id: str,
        page: Page,
    ) -> PageResult[AdminMark]:
        """分页查询某条消息下的有效管理员标记, 已删除的标记不返回"""

        require_admin(user)

        return self.admin_mark_repository.list_by_message(
            message_source_id,
            limit=page.limit,
            offset=page.offset,
        )
