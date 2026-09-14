# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from core.models import User


def is_admin(user: User | None) -> bool:
    """判断用户是否为管理员"""

    return (
        user is not None
        and user.id is not None
        and user.role == "admin"
    )


def is_authenticated(user: User | None) -> bool:
    """判断用户是否已登录"""

    return (
        user is not None
        and user.id is not None
    )


def require_admin(user: User | None) -> None:
    """要求当前用户必须是管理员，否则抛出权限异常"""

    if not is_admin(user):
        raise PermissionError("需要管理员权限")


def require_authenticated(user: User | None) -> None:
    """要求当前用户必须已登录，否则抛出权限异常"""

    if not is_authenticated(user):
        raise PermissionError("需要登录后才能执行此操作")
