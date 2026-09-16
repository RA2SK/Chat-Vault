# 以下为预先准备好的权限校验代码, 不是本文件的主体内容

from datetime import datetime, timezone

from core.enums import UserRole
from core.models import User
from core.types import UserId
from modules.repositories.database import transaction
from modules.repositories.users import UserRepository
from utils.hashing import hash_password, verify_password


def is_admin(user: User | None) -> bool:
    """判断用户是否为管理员"""

    return (
        user is not None
        and user.id is not None
        and user.role == UserRole.ADMIN
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


class UserService:
    """处理用户注册, 认证和信息维护"""

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository


    def register(self, username: str, password: str) -> User:
        """注册一个新用户

        新用户固定为普通用户. 需要创建管理员时使用 `register_admin`,
        避免一个方法承担两种权限等级的创建.
        """

        return self._create_user(username, password, UserRole.USER)


    def register_admin(self, username: str, password: str) -> User:
        """注册一个新管理员

        与 `register` 的唯一区别是角色. 不做任何隐式的"第一个用户升格",
        调用方需要明确表达意图.
        """

        return self._create_user(username, password, UserRole.ADMIN)


    def has_admin(self) -> bool:
        """判断库中是否已有至少一名管理员"""

        return self.user_repository.has_role(UserRole.ADMIN)


    def _create_user(self, username: str, password: str, role: UserRole) -> User:
        """创建用户并落库, 用户名与密码的校验由本方法统一负责"""

        if not username or not password:
            raise ValueError("用户名和密码不能为空")

        user = User(
            username=username,
            password_hash=hash_password(password),
            created_at=datetime.now(timezone.utc),
            role=role,
        )

        # 重名检查与写入放在同一个事务里, 避免两次并发注册都通过检查
        with transaction(self.user_repository.connection):
            if self.user_repository.get_by_username(username) is not None:
                raise ValueError(f"用户名 {username} 已存在")

            self.user_repository.create(user)

        return user


    def authenticate(self, username: str, password: str) -> User | None:
        """校验用户名和密码, 成功时返回用户"""

        user = self.user_repository.get_by_username(username)
        if user is None:
            return None

        if not verify_password(password, user.password_hash):
            return None

        return user


    def get(self, user_id: UserId) -> User | None:
        """根据 ID 获取用户"""

        return self.user_repository.get_by_id(user_id)


    def get_by_username(self, username: str) -> User | None:
        """根据用户名获取用户"""

        return self.user_repository.get_by_username(username)


    def change_password(
        self,
        user: User,
        old_password: str,
        new_password: str,
    ) -> None:
        """校验旧密码后更新用户密码"""

        require_authenticated(user)

        if not verify_password(old_password, user.password_hash):
            raise PermissionError("旧密码不正确")

        if not new_password:
            raise ValueError("新密码不能为空")

        user.password_hash = hash_password(new_password)

        with transaction(self.user_repository.connection):
            self.user_repository.update(user)
