import re
from datetime import datetime, timezone

from core.enums import UserRole
from core.exceptions import (
    ConflictError,
    NotAuthenticatedError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from core.messages import MessageKey
from core.models import User
from core.types import UserId
from modules.interfaces.users_intf import UserView
from modules.repositories.database import transaction
from modules.repositories.users import UserRepository
from utils.hashing import hash_password, verify_password


def is_admin(user: UserView | None) -> bool:
    """判断用户是否为管理员"""

    return (
        user is not None
        and user.id is not None
        and user.role == UserRole.ADMIN
    )


def is_authenticated(user: UserView | None) -> bool:
    """判断用户是否已登录"""

    return (
        user is not None
        and user.id is not None
    )


def require_admin(user: UserView | None) -> None:
    """要求当前用户必须是管理员，否则抛出权限异常"""

    if not is_admin(user):
        raise PermissionDeniedError(MessageKey.ADMIN_REQUIRED)


def require_authenticated(user: UserView | None) -> None:
    """要求当前用户必须已登录，否则抛出权限异常"""

    if not is_authenticated(user):
        raise NotAuthenticatedError(MessageKey.AUTHENTICATION_REQUIRED)


# 用户名允许字母, 数字, 下划线和连字符. 刻意不允许空白和标点:
# 纯空白用户名会创建一个界面上无法复现的"幽灵账号", 而换行等控制字符
# 会破坏单行日志格式.
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# 密码允许字母, 数字和常见符号. 用白名单而不是黑名单: 黑名单永远列不全,
# 而白名单能一次性排除控制字符, 换行, 以及各种同形异义字符.
# 刻意排除引号, 分号, 反斜杠和尖括号: 它们是最典型的注入载荷字符,
# 保留在密码里除了增加输入负担之外没有价值.
# 也刻意排除空格——空格本身合法, 但极易在输入时被误删导致无法登录.
_PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{}.,?/|~]+$")

_USERNAME_MAX_LENGTH = 64

# 密码长度上限. 密码会走 pbkdf2_hmac 十万轮, 一个超长密码会让每次登录
# 消耗可观的 CPU, 是一个廉价的拒绝服务面.
_PASSWORD_MAX_LENGTH = 1024


def validate_username(username: str) -> None:
    """校验用户名, 不合法时抛出 ValidationError

    只做规范化判断, 不修改入参: 调用方拿到的仍是原始字符串.
    """

    if not _USERNAME_PATTERN.match(username):
        raise ValidationError(MessageKey.USERNAME_INVALID)

    if len(username) > _USERNAME_MAX_LENGTH:
        raise ValidationError(
            MessageKey.USERNAME_TOO_LONG,
            max_length=_USERNAME_MAX_LENGTH,
        )


def validate_password(password: str) -> None:
    """校验密码, 不合法时抛出 ValidationError

    刻意不对密码做 strip(): 前后空格是密码的一部分, 剥掉会让用户
    无法用自己设定的密码登录. 空格本身已由白名单排除.
    """

    if not _PASSWORD_PATTERN.match(password):
        raise ValidationError(MessageKey.PASSWORD_INVALID)

    if len(password) > _PASSWORD_MAX_LENGTH:
        raise ValidationError(
            MessageKey.PASSWORD_TOO_LONG,
            max_length=_PASSWORD_MAX_LENGTH,
        )


class UserService:
    """处理用户注册, 认证和信息维护"""

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository


    def register(self, username: str, password: str) -> UserView:
        """注册一个新用户

        新用户固定为普通用户. 需要创建管理员时使用 `register_admin`,
        避免一个方法承担两种权限等级的创建.
        """

        return self._create_user(username, password, UserRole.USER)


    def register_admin(self, username: str, password: str) -> UserView:
        """注册一个新管理员

        与 `register` 的唯一区别是角色. 不做任何隐式的"第一个用户升格",
        调用方需要明确表达意图.
        """

        return self._create_user(username, password, UserRole.ADMIN)


    def has_admin(self) -> bool:
        """判断库中是否已有至少一名管理员"""

        return self.user_repository.has_role(UserRole.ADMIN)


    def _create_user(self, username: str, password: str, role: UserRole) -> UserView:
        """创建用户并落库, 用户名与密码的校验由本方法统一负责

        校验分两层: 先查空值, 再查字符集与长度. 字符集白名单是纵深防御——
        仓储层全部使用参数化查询 (占位符 ``?``), 不存在 SQL 注入路径,
        但用户名会进入日志和响应体, 限制字符集可以避免控制字符破坏日志格式,
        也避免创建出界面上无法复现的账号.
        """

        if not username or not password:
            raise ValidationError(MessageKey.CREDENTIALS_EMPTY)

        validate_username(username)
        validate_password(password)

        user = User(
            username=username,
            password_hash=hash_password(password),
            created_at=datetime.now(timezone.utc),
            role=role,
        )

        # 重名检查与写入放在同一个事务里, 避免两次并发注册都通过检查
        with transaction(self.user_repository.connection):
            if self.user_repository.get_by_username(username) is not None:
                raise ConflictError(
                    MessageKey.USERNAME_ALREADY_EXISTS,
                    username=username,
                )

            self.user_repository.create(user)

        return UserView.from_model(user)


    def authenticate(self, username: str, password: str) -> UserView | None:
        """校验用户名和密码, 成功时返回用户视图

        密码散列只在 `_authenticate_user` 内部出现, 本方法立刻丢掉它.
        """

        user = self._authenticate_user(username, password)
        if user is None:
            return None

        return UserView.from_model(user)


    def _authenticate_user(self, username: str, password: str) -> User | None:
        """校验用户名和密码, 成功时返回领域模型

        只在需要密码散列的流程内部使用, 例如认证成功后签发会话, 或改密前
        确认旧密码. 结果不对外返回.
        """

        user = self.user_repository.get_by_username(username)
        if user is None:
            return None

        if not verify_password(password, user.password_hash):
            return None

        return user


    def get(self, user_id: UserId) -> UserView | None:
        """根据 ID 获取用户"""

        user = self.user_repository.get_by_id(user_id)
        if user is None:
            return None

        return UserView.from_model(user)


    def get_by_username(self, username: str) -> UserView | None:
        """根据用户名获取用户"""

        user = self.user_repository.get_by_username(username)
        if user is None:
            return None

        return UserView.from_model(user)


    def change_password(
        self,
        user: UserView,
        old_password: str,
        new_password: str,
    ) -> None:
        """校验旧密码后更新用户密码

        入参只有视图, 因此按视图中的 id 重新取回领域模型. 这样调用方无法
        通过持有 User 直接绕过校验, 也避免散列出现在契约边界之外.
        """

        require_authenticated(user)

        if not new_password:
            raise ValidationError(MessageKey.NEW_PASSWORD_EMPTY)

        validate_password(new_password)

        # 已知取舍: 不检查新密码是否与旧密码相同. 这不是安全缺陷 (不降低强度),
        # 只是语义上的空操作, 而 "禁止改成相同密码" 本身是产品决策.
        # 若将来需要, 应在此处用 verify_password(new_password, current.password_hash)
        # 判断 (库里存的是散列, 不能做字符串比较), 为真时抛 ValidationError.
        current = self.user_repository.get_by_id(user.id)
        if current is None:
            raise NotFoundError(MessageKey.USER_NOT_FOUND, user_id=user.id)

        if not verify_password(old_password, current.password_hash):
            raise PermissionDeniedError(MessageKey.PASSWORD_INCORRECT)

        current.password_hash = hash_password(new_password)

        with transaction(self.user_repository.connection):
            self.user_repository.update(current)
