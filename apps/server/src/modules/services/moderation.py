# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from datetime import datetime, timezone

from core.enums import MarkType
from core.models import AdminMark, Message, User
from core.types import AdminMarkId
from modules.repositories.moderation import AdminMarkRepository
from modules.repositories.messages import MessageRepository
from modules.services.users import is_admin, require_admin


def can_edit_message(user: User | None, message: Message) -> bool:
    """判断用户是否可以编辑指定消息"""

    return is_admin(user)


def can_create_admin_mark(user: User | None, message: Message) -> bool:
    """判断用户是否可以为消息添加管理员标记"""

    return is_admin(user)


def can_delete_admin_mark(user: User | None, mark: AdminMark) -> bool:
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
        user: User | None,
        message_source_id: str,
        mark_type: MarkType,
    ) -> AdminMark:
        """为消息添加一个管理员标记"""

        require_admin(user)

        message = self.message_repository.get_by_source_id(message_source_id)
        if message is None:
            raise LookupError(f"消息 {message_source_id} 不存在")

        assert user is not None
        mark = AdminMark(
            message_source_id=message_source_id,
            mark_type=mark_type,
            created_at=datetime.now(timezone.utc),
            created_by=user.id,
        )
        self.admin_mark_repository.create(mark)
        return mark


    def remove_mark(self, user: User | None, mark_id: AdminMarkId) -> None:
        """软删除一个管理员标记"""

        require_admin(user)
        self.admin_mark_repository.soft_delete(mark_id)


    def list_marks(self, message_source_id: str) -> list[AdminMark]:
        """查询某条消息下的管理员标记"""

        return [
            mark
            for mark in self.admin_mark_repository.list_by_message(message_source_id)
            if not mark.is_deleted
        ]
