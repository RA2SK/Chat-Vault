"""Comment 的持久化实现

评论不进入内容图内部, 因此只按 source_id 引用对话或消息, 不接触 rowid
"""

import sqlite3
from dataclasses import dataclass

from core.enums import CommentTarget
from core.models import Comment
from core.types import CommentId
from modules.repositories.mappings import to_comment, to_db_datetime


@dataclass
class CommentRepository:
    """Comment 的持久化接口"""

    connection: sqlite3.Connection

    def create(self, comment: Comment) -> None:
        """保存一条评论"""

        if comment.target_type == CommentTarget.CONVERSATION:
            if comment.conversation_source_id is None:
                raise ValueError("对话评论必须设置 conversation_source_id")
            if comment.message_source_id is not None:
                raise ValueError("对话评论不能设置 message_source_id")
        elif comment.target_type == CommentTarget.MESSAGE:
            if comment.message_source_id is None:
                raise ValueError("消息评论必须设置 message_source_id")
            if comment.conversation_source_id is not None:
                raise ValueError("消息评论不能设置 conversation_source_id")
        else:
            raise ValueError("target_type 必须是 conversation 或 message")

        self.connection.execute(
            """
            INSERT INTO comments (
                id,
                conversation_source_id,
                message_source_id,
                target_type,
                content,
                created_at,
                created_by,
                nickname,
                is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                comment.id,
                comment.conversation_source_id,
                comment.message_source_id,
                comment.target_type,
                comment.content,
                to_db_datetime(comment.created_at),
                comment.created_by,
                comment.nickname,
                int(comment.is_deleted),
            ),
        )


    def list_by_conversation(self, conversation_source_id: str) -> list[Comment]:
        """查询某个对话下的评论"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM comments
            WHERE conversation_source_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_source_id,),
        ).fetchall()

        comments: list[Comment] = []
        for row in rows:
            comments.append(to_comment(row))

        return comments


    def list_by_message(self, message_source_id: str) -> list[Comment]:
        """查询某条消息下的评论"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM comments
            WHERE message_source_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (message_source_id,),
        ).fetchall()

        comments: list[Comment] = []
        for row in rows:
            comments.append(to_comment(row))

        return comments


    def soft_delete(self, comment_id: CommentId) -> None:
        """软删除一条评论"""

        self.connection.execute(
            "UPDATE comments SET is_deleted = 1 WHERE id = ?",
            (comment_id,),
        )
