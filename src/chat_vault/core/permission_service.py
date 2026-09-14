"""权限服务的基本框架, 管理用户身份、内容访问和管理操作权限等"""

from dataclasses import dataclass

from chat_vault.core.models import (
    AdminMark,
    Comment,
    Conversation,
    Message,
    User,
)


@dataclass
class PermissionService:
    """为输出端和业务服务提供统一的权限判断入口"""

    def is_admin(self, user: User | None) -> bool:
        """判断用户是否为管理员"""

        return (
            user is not None 
            and user.id is not None 
            and user.role == "admin"
        )


    def is_authenticated(self, user: User | None) -> bool:
        """判断用户是否已登录"""

        return (
            user is not None 
            and user.id is not None
        )


    def can_view_conversation(
        self,
        user: User | None,
        conversation: Conversation,
    ) -> bool:
        """判断用户是否可以查看指定对话"""

        return (
            conversation.is_published 
            or self.is_admin(user)
        )


    def can_publish_conversation(
        self,
        user: User | None,
        conversation: Conversation,
    ) -> bool:
        """判断用户是否可以发布或隐藏指定对话"""

        return self.is_admin(user)


    def can_edit_message(
        self,
        user: User | None,
        message: Message,
    ) -> bool:
        """判断用户是否可以编辑指定消息"""

        return self.is_admin(user)


    def can_create_comment(
        self,
        user: User | None,
        conversation: Conversation,
    ) -> bool:
        """判断用户是否可以在指定对话下创建评论"""

        return (
            self.is_authenticated(user)
            and self.can_view_conversation(user, conversation)
        )


    def can_delete_comment(
        self,
        user: User | None,
        comment: Comment,
    ) -> bool:
        """判断用户是否可以删除评论"""

        return self.is_admin(user)


    def can_create_admin_mark(
        self,
        user: User | None,
        message: Message,
    ) -> bool:
        """判断用户是否可以为消息添加管理员标记"""

        return self.is_admin(user)


    def can_delete_admin_mark(
        self,
        user: User | None,
        mark: AdminMark,
    ) -> bool:
        """判断用户是否可以删除管理员标记"""

        return self.is_admin(user)


    def require_admin(self, user: User | None) -> None:
        """要求当前用户必须是管理员，否则抛出权限异常"""

        if not self.is_admin(user):
            raise PermissionError("需要管理员权限")


    def require_authenticated(self, user: User | None) -> None:
        """要求当前用户必须已登录，否则抛出权限异常"""
        
        if not self.is_authenticated(user):
            raise PermissionError("需要登录后才能执行此操作")

