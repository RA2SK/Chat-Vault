# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from core.models import AdminMark, Message, User
from modules.services.users import is_admin


def can_edit_message(user: User | None, message: Message) -> bool:
    """判断用户是否可以编辑指定消息"""

    return is_admin(user)


def can_create_admin_mark(user: User | None, message: Message) -> bool:
    """判断用户是否可以为消息添加管理员标记"""

    return is_admin(user)


def can_delete_admin_mark(user: User | None, mark: AdminMark) -> bool:
    """判断用户是否可以删除管理员标记"""

    return is_admin(user)
