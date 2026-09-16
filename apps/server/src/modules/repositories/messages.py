"""Message 与 Attachment 的持久化实现

Attachment 以 (message_source_id, source_ref) 作为身份, 不额外引入代理 id
"""

import sqlite3
from dataclasses import dataclass
from typing import Iterator

from core.exceptions import NotFoundError
from core.messages import MessageKey
from core.models import Attachment, Message
from core.pagination import PageResult
from modules.repositories.mappings import (
    to_attachment,
    to_db_checksum,
    to_db_datetime,
    to_message,
)

# SQLite 的 SQLITE_MAX_VARIABLE_NUMBER 在 3.32 之后默认是 32766, 但旧版本是 999.
# 取 500 是一个远低于任何版本上限的值, 同时保证单条 SQL 的文本长度可控.
_MAX_SQL_VARIABLES = 500


def _chunked(values: list[str], size: int) -> Iterator[list[str]]:
    """把列表切成固定大小的批次, 供 IN (...) 查询使用"""

    for start in range(0, len(values), size):
        yield values[start:start + size]


@dataclass
class MessageRepository:
    """Message 的持久化接口"""

    connection: sqlite3.Connection

    def _branch_rowid(self, branch_source_id: str) -> int:
        """把分支的 source_id 解析成内容图内部使用的 rowid, 父节点不存在时立刻抛出错误"""

        row = self.connection.execute(
            "SELECT id FROM branches WHERE source_id = ?",
            (branch_source_id,),
        ).fetchone()

        if row is None:
            raise NotFoundError(
                MessageKey.BRANCH_NOT_FOUND,
                branch_source_id=branch_source_id,
            )

        return row["id"]


    def create(self, message: Message, branch_source_id: str) -> None:
        """保存一条消息, 并挂到指定分支下"""

        branch_rowid = self._branch_rowid(branch_source_id)

        self.connection.execute(
            """
            INSERT INTO messages (
                branch_id,
                source_id,
                role,
                content,
                thinking,
                model,
                position,
                timestamp,
                edited_at,
                edited_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                branch_rowid,
                message.source_id,
                message.role,
                message.content,
                message.thinking,
                message.model,
                message.position,
                to_db_datetime(message.timestamp),
                to_db_datetime(message.edited_at),
                message.edited_by,
            ),
        )


    def get_by_source_id(self, source_id: str) -> Message | None:
        """根据来源 ID 查询消息"""

        row = self.connection.execute(
            "SELECT * FROM messages WHERE source_id = ?",
            (source_id,),
        ).fetchone()

        if row is None:
            return None

        return to_message(row)


    def get_conversation_source_id(self, message_source_id: str) -> str | None:
        """查询消息所属对话的 source_id"""

        row = self.connection.execute(
            """
            SELECT conversations.source_id
            FROM messages
            JOIN branches ON branches.id = messages.branch_id
            JOIN conversations ON conversations.id = branches.conversation_id
            WHERE messages.source_id = ?
            """,
            (message_source_id,),
        ).fetchone()

        if row is None:
            return None

        return row[0]


    def list_by_branch(
        self,
        branch_source_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> PageResult[Message]:
        """按 position 顺序查询某个分支下的消息

        limit 为 None 表示不分页, 供详情查询和内部调用方取全量
        """

        if limit is None:
            rows = self.connection.execute(
                """
                SELECT *
                FROM messages
                WHERE branch_id = (
                    SELECT id FROM branches WHERE source_id = ?
                )
                ORDER BY position ASC, id ASC
                """,
                (branch_source_id,),
            ).fetchall()
            return PageResult(items=[to_message(row) for row in rows])

        rows = self.connection.execute(
            """
            SELECT *
            FROM messages
            WHERE branch_id = (
                SELECT id FROM branches WHERE source_id = ?
            )
            ORDER BY position ASC, id ASC
            LIMIT ? OFFSET ?
            """,
            (branch_source_id, limit + 1, offset),
        ).fetchall()

        return PageResult(
            items=[to_message(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )


    def list_by_branches(
        self,
        branch_source_ids: list[str],
    ) -> dict[str, list[Message]]:
        """一次查询多个分支下的消息, 按分支来源 ID 分组返回

        存在的意义是消除详情查询的 N+1: 逐个分支调用 list_by_branch 会让
        一个有 3 个分支的对话产生 3 次查询, 而这里只需要 1 次.

        参数个数超过 SQLite 的变量上限时按批切分, 因此调用方不需要关心
        分支数量. 返回的字典只包含有消息的分支, 调用方用 get 取默认空列表.
        """

        grouped: dict[str, list[Message]] = {}

        for chunk in _chunked(branch_source_ids, _MAX_SQL_VARIABLES):
            placeholders = ", ".join("?" for _ in chunk)
            rows = self.connection.execute(
                f"""
                SELECT messages.*, branches.source_id AS branch_source_id
                FROM messages
                JOIN branches ON branches.id = messages.branch_id
                WHERE branches.source_id IN ({placeholders})
                ORDER BY messages.position ASC, messages.id ASC
                """,
                tuple(chunk),
            ).fetchall()

            for row in rows:
                grouped.setdefault(row["branch_source_id"], []).append(
                    to_message(row),
                )

        return grouped


    def update(self, message: Message) -> None:
        """更新一条消息的正文与编辑信息, 不改变它所属的分支"""

        self.connection.execute(
            """
            UPDATE messages
            SET role = ?,
                content = ?,
                thinking = ?,
                model = ?,
                position = ?,
                timestamp = ?,
                edited_at = ?,
                edited_by = ?
            WHERE source_id = ?
            """,
            (
                message.role,
                message.content,
                message.thinking,
                message.model,
                message.position,
                to_db_datetime(message.timestamp),
                to_db_datetime(message.edited_at),
                message.edited_by,
                message.source_id,
            ),
        )


@dataclass
class AttachmentRepository:
    """Attachment 的持久化接口"""

    connection: sqlite3.Connection

    def _message_rowid(self, message_source_id: str) -> int:
        """把消息的 source_id 解析成内容图内部使用的 rowid

        显式预校验: 父节点不存在时立刻抛出可读的错误, 而不是让外键约束在提交时报错
        """

        row = self.connection.execute(
            "SELECT id FROM messages WHERE source_id = ?",
            (message_source_id,),
        ).fetchone()

        if row is None:
            raise NotFoundError(
                MessageKey.MESSAGE_ATTACHMENT_ANCHOR_MISSING,
                message_source_id=message_source_id,
            )

        return row["id"]


    def create(self, attachment: Attachment) -> None:
        """保存一个附件, 并挂到 message_source_id 对应的消息下"""

        message_rowid = self._message_rowid(attachment.message_source_id)
        checksum_algorithm, checksum_value = to_db_checksum(attachment.checksum)

        self.connection.execute(
            """
            INSERT INTO attachments (
                message_id,
                message_source_id,
                attach_type,
                source_ref,
                display_name,
                mime_type,
                checksum_algorithm,
                checksum_value,
                size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_rowid,
                attachment.message_source_id,
                attachment.attach_type,
                attachment.source_ref,
                attachment.display_name,
                attachment.mime_type,
                checksum_algorithm,
                checksum_value,
                attachment.size,
            ),
        )


    def list_by_message(self, message_source_id: str) -> list[Attachment]:
        """查询某条消息下的所有附件, 按插入顺序返回"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM attachments
            WHERE message_source_id = ?
            ORDER BY rowid ASC
            """,
            (message_source_id,),
        ).fetchall()

        attachments: list[Attachment] = []
        for row in rows:
            attachments.append(to_attachment(row))

        return attachments


    def list_by_messages(
        self,
        message_source_ids: list[str],
    ) -> dict[str, list[Attachment]]:
        """一次查询多条消息下的附件, 按消息来源 ID 分组返回

        与 MessageRepository.list_by_branches 同理: 逐个消息调用
        list_by_message 会让一个有 2000 条消息的对话产生 2000 次查询,
        而这里只需要 1 次.
        """

        grouped: dict[str, list[Attachment]] = {}

        for chunk in _chunked(message_source_ids, _MAX_SQL_VARIABLES):
            placeholders = ", ".join("?" for _ in chunk)
            rows = self.connection.execute(
                f"""
                SELECT *
                FROM attachments
                WHERE message_source_id IN ({placeholders})
                ORDER BY rowid ASC
                """,
                tuple(chunk),
            ).fetchall()

            for row in rows:
                grouped.setdefault(row["message_source_id"], []).append(
                    to_attachment(row),
                )

        return grouped


    def update(self, attachment: Attachment) -> None:
        """更新一个附件的可编辑字段, 不改变它所属的消息"""

        checksum_algorithm, checksum_value = to_db_checksum(attachment.checksum)

        self.connection.execute(
            """
            UPDATE attachments
            SET attach_type = ?,
                display_name = ?,
                mime_type = ?,
                checksum_algorithm = ?,
                checksum_value = ?,
                size = ?
            WHERE message_source_id = ? AND source_ref = ?
            """,
            (
                attachment.attach_type,
                attachment.display_name,
                attachment.mime_type,
                checksum_algorithm,
                checksum_value,
                attachment.size,
                attachment.message_source_id,
                attachment.source_ref,
            ),
        )


    def delete(self, message_source_id: str, source_ref: str) -> None:
        """删除一个附件"""

        self.connection.execute(
            """
            DELETE FROM attachments
            WHERE message_source_id = ? AND source_ref = ?
            """,
            (message_source_id, source_ref),
        )
