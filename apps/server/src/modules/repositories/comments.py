"""Comment 的持久化实现

评论不进入内容图内部, 因此只按 source_id 引用对话或消息, 不接触 rowid
"""

import sqlite3
from dataclasses import dataclass

from core.enums import CommentTarget
from core.exceptions import ValidationError
from core.messages import MessageKey
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
                raise ValidationError(
                    MessageKey.COMMENT_CONVERSATION_TARGET_REQUIRED
                )
            if comment.message_source_id is not None:
                raise ValidationError(
                    MessageKey.COMMENT_CONVERSATION_TARGET_FORBIDDEN
                )
        elif comment.target_type == CommentTarget.MESSAGE:
            if comment.message_source_id is None:
                raise ValidationError(MessageKey.COMMENT_MESSAGE_TARGET_REQUIRED)
            if comment.conversation_source_id is not None:
                raise ValidationError(MessageKey.COMMENT_MESSAGE_TARGET_FORBIDDEN)
        else:
            raise ValidationError(MessageKey.COMMENT_TARGET_INVALID)

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
        """查询直接挂在某个对话下的有效评论

        只匹配 conversation_source_id, 不包含该对话所属消息的评论,
        因为消息级评论的 conversation_source_id 为空. 需要覆盖消息评论时
        使用 `list_by_conversation_including_messages`.
        """

        rows = self.connection.execute(
            """
            SELECT *
            FROM comments
            WHERE conversation_source_id = ?
              AND is_deleted = 0
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_source_id,),
        ).fetchall()

        comments: list[Comment] = []
        for row in rows:
            comments.append(to_comment(row))

        return comments


    def list_by_conversation_including_messages(
        self,
        conversation_source_id: str,
    ) -> list[Comment]:
        """查询某个对话下的全部有效评论, 含该对话所属消息的评论

        消息级评论在库内不记录所属对话, 因此这里沿
        comments -> messages -> branches -> conversations 逐级回溯归属.

        刻意拆成两条查询而不是一条带 OR 的联表查询: 原来的写法把
        `comments.conversation_source_id = ?` 和 `conversations.source_id = ?`
        放在同一个 OR 里, 优化器无法用上 idx_comments_conversation 和
        idx_comments_message, 只能全表扫 comments 再逐行联表. 拆开之后两条
        查询各自都能走索引, 合并与排序在内存里做, 数据量是"这个对话下的评论
        数", 而不是"全库评论数".
        """

        conversation_comments = self.connection.execute(
            """
            SELECT *
            FROM comments
            WHERE conversation_source_id = ?
              AND is_deleted = 0
            """,
            (conversation_source_id,),
        ).fetchall()

        message_comments = self.connection.execute(
            """
            SELECT comments.*
            FROM comments
            JOIN messages
                ON messages.source_id = comments.message_source_id
            JOIN branches
                ON branches.id = messages.branch_id
            JOIN conversations
                ON conversations.id = branches.conversation_id
            WHERE conversations.source_id = ?
              AND comments.is_deleted = 0
            """,
            (conversation_source_id,),
        ).fetchall()

        comments = [to_comment(row) for row in conversation_comments]
        comments.extend(to_comment(row) for row in message_comments)

        # 时间相同时按 id 兜底, 保证同一批数据每次返回的顺序一致
        comments.sort(key=lambda comment: (comment.created_at, comment.id))

        return comments


    def list_by_message(self, message_source_id: str) -> list[Comment]:
        """查询某条消息下的有效评论"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM comments
            WHERE message_source_id = ?
              AND is_deleted = 0
            ORDER BY created_at ASC, id ASC
            """,
            (message_source_id,),
        ).fetchall()

        comments: list[Comment] = []
        for row in rows:
            comments.append(to_comment(row))

        return comments


    def soft_delete(self, comment_id: CommentId) -> bool:
        """软删除一条评论, 返回是否真的删掉了一行

        返回布尔值而不是静默成功: 调用方需要区分"删掉了"和"这条评论根本
        不存在", 后者应当报 404 而不是假装成功.
        """

        cursor = self.connection.execute(
            "UPDATE comments SET is_deleted = 1 WHERE id = ? AND is_deleted = 0",
            (comment_id,),
        )

        return cursor.rowcount > 0
