"""用户能力契约, 定义用户注册, 认证和信息维护

本模块同时声明对外暴露的用户形状. 核心的 `User` 模型带有 `password_hash`,
它是持久化细节, 不应该出现在任何对外结果中, 因此对外一律使用 `UserView`.

用户服务对外只返回 `UserView`. 需要密码散列的只有认证和改密两个内部流程,
它们在实现内部自行从仓储取回 `User`, 散列不会穿过契约边界.

权限判断函数 (is_admin, require_admin 等) 留在服务层, 不进入契约:
它们是跨服务复用的真实逻辑, 且属于实现细节而非调用契约. 它们接收
`UserView | None`, 因为判断权限只需要 `id` 和 `role` 两个字段.

真正的会话管理和持久化权限体系尚未实现, 因此本模块不声明会话相关调用,
`SessionStore` 只是先占位的形状约定.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from core.enums import UserRole
from core.models import User
from core.types import UserId


@dataclass
class UserView:
    """对外暴露的用户信息, 不含密码散列"""

    id: UserId
    username: str
    role: UserRole
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, user: User) -> "UserView":
        """把领域模型转换成对外视图, 只复制允许暴露的字段

        刻意逐字段复制而不是 `dataclasses.asdict`: 只有显式列举的字段才可能
        越过契约边界, `User` 以后新增字段时不会因为疏忽而被自动带出去.
        """

        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            created_at=user.created_at,
        )


@dataclass
class UserRegistration:
    """注册一个新用户的输入"""

    username: str
    password: str


@dataclass
class PasswordChange:
    """修改密码的输入, 需要同时提供旧密码以确认身份"""

    old_password: str
    new_password: str


@runtime_checkable
class IdGenerator(Protocol):
    """应用侧标识符生成能力

    `core.types.new_id()` 满足本契约, 测试中也可以注入可预测的替身.
    目前只有评论, 标记和导入批次使用应用侧标识符, 内容域以 source_id 为身份.
    """

    def __call__(self) -> str:
        """生成一个新的标识符字符串"""
        ...


@runtime_checkable
class SessionStore(Protocol):
    """登录会话的存放约定, 供后续接入认证系统时使用

    目前没有实现, 也没有任何调用方, 先声明形状以便上层依赖不推迟到以后才设计.
    """

    def create(self, user_id: UserId, token: str, expires_at: datetime) -> None:
        """保存一个会话"""
        ...

    def resolve(self, token: str) -> UserId | None:
        """根据令牌解析出用户 ID, 令牌无效或已过期时返回 None"""
        ...

    def revoke(self, token: str) -> None:
        """注销一个会话"""
        ...


class UserServiceContract(Protocol):
    """用户能力契约

    具体实现的构造依赖为: 用户仓储契约.

    刻意不提供"列出全部用户"的调用: 该能力在业务上不需要, 提供它会扩大
    用户信息的暴露面. 需要判断管理员是否存在时使用 `has_admin`.
    """

    def register(self, username: str, password: str) -> UserView:
        """注册一个新用户

        用户名或密码为空时抛出 ValidationError, 用户名已存在时抛出 ConflictError.
        实现固定把新用户设为普通用户, 不接受调用方指定角色.
        需要创建管理员时使用 `register_admin`.
        """
        ...

    def register_admin(self, username: str, password: str) -> UserView:
        """注册一个新管理员

        校验规则与 `register` 相同, 唯一区别是角色为管理员.
        实现不做任何隐式的"第一个用户升格", 调用方需要明确表达意图.
        """
        ...

    def has_admin(self) -> bool:
        """判断库中是否已有至少一名管理员

        供启动自检使用. 刻意不提供"列出全部用户"的调用: 该能力在业务上
        不需要, 提供它会扩大用户信息的暴露面.
        """
        ...

    def authenticate(self, username: str, password: str) -> UserView | None:
        """校验用户名和密码, 成功时返回用户视图, 失败时返回 None

        认证需要读取密码散列, 但散列不进入返回值, 因此失败时返回 None 而不是
        区分"用户不存在"和"密码错误", 避免泄露用户名是否存在.
        """
        ...

    def get(self, user_id: UserId) -> UserView | None:
        """根据 ID 获取用户"""
        ...

    def get_by_username(self, username: str) -> UserView | None:
        """根据用户名获取用户"""
        ...

    def change_password(
        self,
        user: UserView,
        old_password: str,
        new_password: str,
    ) -> None:
        """校验旧密码后更新用户密码

        只接收 `UserView`, 由实现内部按视图中的 id 取回领域模型后再接触散列.
        用户未登录时抛出 NotAuthenticatedError, 旧密码不正确时抛出 PermissionDeniedError,
        新密码为空时抛出 ValidationError, 用户已不存在时抛出 NotFoundError
        """
        ...


__all__ = [
    "IdGenerator",
    "PasswordChange",
    "SessionStore",
    "UserRegistration",
    "UserServiceContract",
    "UserView",
]