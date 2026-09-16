"""Conversation 与 Branch 的持久化实现

内容图内部用自增 rowid 维持父子外键, rowid 不进入模型也不离开本层,
对外一律以 source_id 标识; 需要写父子关系时由调用方显式传入父节点的 source_id
"""

import sqlite3
from dataclasses import dataclass

from core.exceptions import NotFoundError
from core.messages import MessageKey
from core.models import Branch, Conversation
from core.pagination import PageResult
from modules.repositories.mappings import to_branch, to_conversation, to_db_datetime


@dataclass
class ConversationRepository:
    """Conversation 的持久化接口"""

    connection: sqlite3.Connection

    def create(self, conversation: Conversation) -> None:
        """保存一个对话"""

        self.connection.execute(
            """
            INSERT INTO conversations (
                source_type,
                source_id,
                title,
                source_archive,
                source_entry,
                created_at,
                updated_at,
                is_published,
                import_batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation.source_type,
                conversation.source_id,
                conversation.title,
                conversation.source_archive,
                conversation.source_entry,
                to_db_datetime(conversation.created_at),
                to_db_datetime(conversation.updated_at),
                int(conversation.is_published),
                conversation.import_batch_id,
            ),
        )


    def get_by_source_id(self, source_id: str) -> Conversation | None:
        """根据来源 ID 查询对话"""

        row = self.connection.execute(
            "SELECT * FROM conversations WHERE source_id = ?",
            (source_id,),
        ).fetchone()

        if row is None:
            return None

        return to_conversation(row)


    def update(self, conversation: Conversation) -> None:
        """更新一个对话

        刻意不写 created_at / updated_at: 时间戳由导入层按备份内容决定, 是
        数据的一部分, 不是"这次写入发生在什么时候". 让 update 顺手刷新时间戳
        会把重复导入变成一次内容变更, 也会让时间戳失去可追溯性.
        """

        self.connection.execute(
            """
            UPDATE conversations
            SET source_type = ?,
                title = ?,
                source_archive = ?,
                source_entry = ?,
                is_published = ?,
                import_batch_id = ?
            WHERE source_id = ?
            """,
            (
                conversation.source_type,
                conversation.title,
                conversation.source_archive,
                conversation.source_entry,
                int(conversation.is_published),
                conversation.import_batch_id,
                conversation.source_id,
            ),
        )


    def list_all(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> PageResult[Conversation]:
        """查询所有对话

        limit 为 None 表示不分页, 供命令行和内部调用方取全量. 分页时多取
        一行来判断 has_more, 避免额外一次 COUNT(*) 全表扫描.
        """

        if limit is None:
            rows = self.connection.execute(
                """
                SELECT *
                FROM conversations
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
            return PageResult(items=[to_conversation(row) for row in rows])

        rows = self.connection.execute(
            """
            SELECT *
            FROM conversations
            ORDER BY updated_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit + 1, offset),
        ).fetchall()

        return PageResult(
            items=[to_conversation(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )


    def list_published(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> PageResult[Conversation]:
        """查询所有已发布的对话"""

        if limit is None:
            rows = self.connection.execute(
                """
                SELECT *
                FROM conversations
                WHERE is_published = 1
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
            return PageResult(items=[to_conversation(row) for row in rows])

        rows = self.connection.execute(
            """
            SELECT *
            FROM conversations
            WHERE is_published = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit + 1, offset),
        ).fetchall()

        return PageResult(
            items=[to_conversation(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )


@dataclass
class BranchRepository:
    """Branch 的持久化接口"""

    connection: sqlite3.Connection

    def _conversation_rowid(self, conversation_source_id: str) -> int:
        """把对话的 source_id 解析成内容图内部使用的 rowid

        显式预校验: 父节点不存在时立刻抛出可读的错误, 而不是让外键约束在提交时报错
        """

        row = self.connection.execute(
            "SELECT id FROM conversations WHERE source_id = ?",
            (conversation_source_id,),
        ).fetchone()

        if row is None:
            raise NotFoundError(
                MessageKey.CONVERSATION_BRANCH_ANCHOR_MISSING,
                conversation_source_id=conversation_source_id,
            )

        return row["id"]


    def create(self, branch: Branch, conversation_source_id: str) -> None:
        """保存一个分支, 并挂到指定对话下"""

        conversation_rowid = self._conversation_rowid(conversation_source_id)

        self.connection.execute(
            """
            INSERT INTO branches (
                conversation_id,
                source_id,
                branch_index,
                fork_message_source_id,
                created_at,
                updated_at,
                is_current
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_rowid,
                branch.source_id,
                branch.index,
                branch.fork_message_source_id,
                to_db_datetime(branch.created_at),
                to_db_datetime(branch.updated_at),
                int(branch.is_current),
            ),
        )


    def get_by_source_id(self, source_id: str) -> Branch | None:
        """根据来源 ID 查询分支"""

        row = self.connection.execute(
            "SELECT * FROM branches WHERE source_id = ?",
            (source_id,),
        ).fetchone()

        if row is None:
            return None

        return to_branch(row)


    def update(self, branch: Branch) -> None:
        """更新一个分支

        不改变分支所属的对话: 分支归属由首次导入时的对话决定, 迁移分支
        属于内容图重构, 不属于重复导入的处理范围.

        与对话的 update 同理, 这里不写 created_at / updated_at: 时间戳由导入层
        按备份内容决定, 不是写入时刻.
        """

        self.connection.execute(
            """
            UPDATE branches
            SET branch_index = ?,
                fork_message_source_id = ?,
                is_current = ?
            WHERE source_id = ?
            """,
            (
                branch.index,
                branch.fork_message_source_id,
                int(branch.is_current),
                branch.source_id,
            ),
        )


    def list_by_conversation(self, conversation_source_id: str) -> list[Branch]:
        """查询某个对话下的所有分支"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM branches
            WHERE conversation_id = (
                SELECT id FROM conversations WHERE source_id = ?
            )
            ORDER BY branch_index ASC, id ASC
            """,
            (conversation_source_id,),
        ).fetchall()

        branches: list[Branch] = []
        for row in rows:
            branches.append(to_branch(row))

        return branches
