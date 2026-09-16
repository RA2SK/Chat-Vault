"""User 的持久化实现"""

import sqlite3
from dataclasses import dataclass

from core.enums import UserRole
from core.models import User
from core.types import UserId
from modules.repositories.mappings import to_db_datetime, to_user


@dataclass
class UserRepository:
    """User 的持久化接口"""

    connection: sqlite3.Connection

    def create(self, user: User) -> None:
        """保存一个用户"""

        self.connection.execute(
            """
            INSERT INTO users (
                id,
                username,
                password_hash,
                created_at,
                role
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.username,
                user.password_hash,
                to_db_datetime(user.created_at),
                user.role,
            ),
        )


    def get_by_id(self, user_id: UserId) -> User | None:
        """根据 ID 查询用户"""

        row = self.connection.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            return None

        return to_user(row)


    def get_by_username(self, username: str) -> User | None:
        """根据用户名查询用户"""

        row = self.connection.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if row is None:
            return None

        return to_user(row)


    def has_role(self, role: UserRole) -> bool:
        """判断是否存在至少一个指定角色的用户

        刻意只回答"有没有", 不提供"列出全部用户": 前者是启动自检需要的能力,
        后者会扩大用户信息的暴露面.
        """

        row = self.connection.execute(
            "SELECT 1 FROM users WHERE role = ? LIMIT 1",
            (role,),
        ).fetchone()

        return row is not None


    def update(self, user: User) -> None:
        """更新一个用户"""

        self.connection.execute(
            """
            UPDATE users
            SET username = ?,
                password_hash = ?,
                created_at = ?,
                role = ?
            WHERE id = ?
            """,
            (
                user.username,
                user.password_hash,
                to_db_datetime(user.created_at),
                user.role,
                user.id,
            ),
        )
