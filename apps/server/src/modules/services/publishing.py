# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from core.models import Conversation, User
from modules.services.users import is_admin


def can_view_conversation(user: User | None, conversation: Conversation) -> bool:
    """判断用户是否可以查看指定对话"""

    return (
        conversation.is_published
        or is_admin(user)
    )


def can_publish_conversation(user: User | None, conversation: Conversation) -> bool:
    """判断用户是否可以发布或隐藏指定对话"""

    return is_admin(user)
