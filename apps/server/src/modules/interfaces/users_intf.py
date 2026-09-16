"""用户能力契约, 定义用户注册, 认证和信息维护

本模块同时声明对外暴露的用户形状. 核心的 `User` 模型带有 `password_hash`,
它是持久化细节, 不应该出现在任何对外结果中, 因此对外一律使用 `UserView`.

`UserView` 是目标形状. 当前 `UserService.register` 和 `UserService.get`
仍然返回完整的 `User`, 尚未做字段剥离, 因此契约暂时按现状声明返回类型,
待用户信息整理逻辑实现后再收窄为视图类型.

权限判断函数 (is_admin, require_admin 等) 留在服务层, 不进入契约:
它们是跨服务复用的真实逻辑, 且属于实现细节而非调用契约.

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
    用户信息的暴露面.
    """

    def register(self, username: str, password: str) -> User:
        """注册一个新用户

        用户名或密码为空时抛出 ValueError, 用户名已存在时抛出 ValueError.
        实现固定把新用户设为普通用户, 不接受调用方指定角色.
        """
        ...

    def authenticate(self, username: str, password: str) -> User | None:
        """校验用户名和密码, 成功时返回用户, 失败时返回 None"""
        ...

    def get(self, user_id: UserId) -> User | None:
        """根据 ID 获取用户"""
        ...

    def get_by_username(self, username: str) -> User | None:
        """根据用户名获取用户"""
        ...

    def change_password(
        self,
        user: User,
        old_password: str,
        new_password: str,
    ) -> None:
        """校验旧密码后更新用户密码

        用户未登录时抛出 PermissionError, 旧密码不正确时抛出 PermissionError,
        新密码为空时抛出 ValueError
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