"""Message 与 Attachment 的持久化实现

Attachment 以 (message_source_id, source_ref) 作为身份, 不额外引入代理 id
"""

import sqlite3
from dataclasses import dataclass

from core.exceptions import NotFoundError
from core.messages import MessageKey
from core.models import Attachment, Message
from modules.repositories.mappings import (
    to_attachment,
    to_db_checksum,
    to_db_datetime,
    to_message,
)


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


    def list_by_branch(self, branch_source_id: str) -> list[Message]:
        """按 position 顺序查询某个分支下的消息"""

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

        messages: list[Message] = []
        for row in rows:
            messages.append(to_message(row))

        return messages


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
