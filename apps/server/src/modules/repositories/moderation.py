"""AdminMark 的持久化实现

管理员标记不进入内容图内部, 因此只按 source_id 引用消息, 不接触 rowid
"""

import sqlite3
from dataclasses import dataclass

from core.models import AdminMark
from core.types import AdminMarkId
from modules.repositories.mappings import to_admin_mark, to_db_datetime


@dataclass
class AdminMarkRepository:
    """AdminMark 的持久化接口"""

    connection: sqlite3.Connection

    def create(self, mark: AdminMark) -> None:
        """保存一个管理员标记"""

        self.connection.execute(
            """
            INSERT INTO admin_marks (
                id,
                message_source_id,
                mark_type,
                created_at,
                created_by,
                is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                mark.id,
                mark.message_source_id,
                mark.mark_type,
                to_db_datetime(mark.created_at),
                mark.created_by,
                int(mark.is_deleted),
            ),
        )


    def list_by_message(self, message_source_id: str) -> list[AdminMark]:
        """查询某条消息下的有效管理员标记, 已删除的标记不返回"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM admin_marks
            WHERE message_source_id = ? AND is_deleted = 0
            ORDER BY created_at ASC, id ASC
            """,
            (message_source_id,),
        ).fetchall()

        marks: list[AdminMark] = []
        for row in rows:
            marks.append(to_admin_mark(row))

        return marks


    def soft_delete(self, mark_id: AdminMarkId) -> None:
        """软删除一个管理员标记"""

        self.connection.execute(
            "UPDATE admin_marks SET is_deleted = 1 WHERE id = ?",
            (mark_id,),
        )
