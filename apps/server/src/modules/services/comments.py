# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from core.models import Comment, Conversation, User
from modules.services.publishing import can_view_conversation
from modules.services.users import is_admin, is_authenticated


def can_create_comment(user: User | None, conversation: Conversation) -> bool:
    """判断用户是否可以在指定对话下创建评论"""

    return (
        is_authenticated(user)
        and can_view_conversation(user, conversation)
    )


def can_delete_comment(user: User | None, comment: Comment) -> bool:
    """判断用户是否可以删除评论"""

    return is_admin(user)
