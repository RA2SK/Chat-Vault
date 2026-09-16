"""Comment 的持久化实现

评论不进入内容图内部, 因此只按 source_id 引用对话或消息, 不接触 rowid
"""

import sqlite3
from dataclasses import dataclass

from core.enums import CommentTarget
from core.exceptions import ValidationError
from core.messages import MessageKey
from core.models import Comment
from core.pagination import PageResult
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
        limit: int | None = None,
        offset: int = 0,
    ) -> PageResult[Comment]:
        """查询某个对话下的全部有效评论, 含该对话所属消息的评论

        消息级评论在库内不记录所属对话, 因此这里沿
        comments -> messages -> branches -> conversations 逐级回溯归属.

        用 UNION ALL 把两条查询合成一个子查询, 再在外层统一排序和分页.
        不能像以前那样在 Python 里合并排序: 那样必须先取出全部评论才能
        切出第 N 页, 分页就失去了意义.

        两个分支各自仍然能走索引: 第一个分支用 idx_comments_conversation,
        第二个分支从 conversations 出发沿 idx_branches_conversation 和
        idx_messages_branch_position 回溯, 再走 idx_comments_message.
        这正是当初拆成两条查询而不是写一个带 OR 的联表查询的原因, 现在
        只是把"拆开"从 Python 层移到了 SQL 层.
        """

        if limit is None:
            rows = self.connection.execute(
                """
                SELECT * FROM (
                    SELECT *
                    FROM comments
                    WHERE conversation_source_id = ?
                      AND is_deleted = 0
                    UNION ALL
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
                )
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_source_id, conversation_source_id),
            ).fetchall()
            return PageResult(items=[to_comment(row) for row in rows])

        rows = self.connection.execute(
            """
            SELECT * FROM (
                SELECT *
                FROM comments
                WHERE conversation_source_id = ?
                  AND is_deleted = 0
                UNION ALL
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
            )
            ORDER BY created_at ASC, id ASC
            LIMIT ? OFFSET ?
            """,
            (conversation_source_id, conversation_source_id, limit + 1, offset),
        ).fetchall()

        return PageResult(
            items=[to_comment(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )


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
