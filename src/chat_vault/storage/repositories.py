"""面向核心模型的数据仓储接口"""

from dataclasses import dataclass
from datetime import datetime
import sqlite3

from chat_vault.core.models import (
    AdminMark,
    Attachment,
    Branch,
    Comment,
    Conversation,
    ImportBatch,
    Message,
    User,
    Checksum
)


@dataclass
class ImportBatchRepository:
    """ImportBatch 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _datetime_to_database(value: datetime | None) -> str | None:
        """将 Python datetime 转换为 SQLite 中保存的文本"""

        if value is None:
            return None

        return value.isoformat()


    @staticmethod
    def _datetime_from_database(value: str) -> datetime:
        """将 SQLite 中保存的 ISO 文本转换为 Python datetime"""

        return datetime.fromisoformat(value)


    @staticmethod
    def _row_to_import_batch(row: sqlite3.Row) -> ImportBatch:
        """将数据库行转换为 ImportBatch"""

        import_batch = ImportBatch(
            file_name=row["file_name"],
            file_hash=row["file_hash"],
            started_at=ImportBatchRepository._datetime_from_database(
                row["started_at"]
            ),
            status=row["status"],
            total_count=row["total_count"],
            success_count=row["success_count"],
            failed_count=row["failed_count"],
            source_type=row["source_type"],
            format_key=row["format_key"],
            id=row["id"],
            error_summary=row["error_summary"],
            finished_at=(
                None
                if row["finished_at"] is None
                else ImportBatchRepository._datetime_from_database(
                    row["finished_at"]
                )
            ),
        )

        return import_batch


    def create(self, import_batch: ImportBatch) -> int:
        """保存一个导入批次, 并返回数据库 ID"""

        cursor = self.connection.execute(
            """
            INSERT INTO import_batches (
                file_name,
                file_hash,
                started_at,
                finished_at,
                status,
                total_count,
                success_count,
                failed_count,
                source_type,
                format_key,
                error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_batch.file_name,
                import_batch.file_hash,
                self._datetime_to_database(import_batch.started_at),
                self._datetime_to_database(import_batch.finished_at),
                import_batch.status,
                import_batch.total_count,
                import_batch.success_count,
                import_batch.failed_count,
                import_batch.source_type,
                import_batch.format_key,
                import_batch.error_summary,
            ),
        )

        import_batch.id = cursor.lastrowid
        if import_batch.id is None:
            raise RuntimeError("保存导入批次后未获得数据库 ID")

        return import_batch.id


    def get_by_id(self, import_batch_id: int) -> ImportBatch | None:
        """根据数据库 ID 查询导入批次"""

        row = self.connection.execute(
            "SELECT * FROM import_batches WHERE id = ?",
            (import_batch_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_import_batch(row)


    def update(self, import_batch: ImportBatch) -> None:
        """更新一个导入批次"""
        
        if import_batch.id is None:
            raise ValueError("更新导入批次前必须存在数据库 ID")

        self.connection.execute(
            """
            UPDATE import_batches
            SET file_name = ?,
                file_hash = ?,
                started_at = ?,
                finished_at = ?,
                status = ?,
                total_count = ?,
                success_count = ?,
                failed_count = ?,
                source_type = ?,
                format_key = ?,
                error_summary = ?
            WHERE id = ?
            """,
            (
                import_batch.file_name,
                import_batch.file_hash,
                self._datetime_to_database(import_batch.started_at),
                self._datetime_to_database(import_batch.finished_at),
                import_batch.status,
                import_batch.total_count,
                import_batch.success_count,
                import_batch.failed_count,
                import_batch.source_type,
                import_batch.format_key,
                import_batch.error_summary,
                import_batch.id,
            ),
        )


@dataclass
class ConversationRepository:
    """Conversation 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _datetime_to_database(value: datetime | None) -> str | None:
        """将 Python datetime 转换为 SQLite 中保存的文本"""
        
        if value is None:
            return None

        return value.isoformat()  


    @staticmethod
    def _datetime_from_database(value: str | None) -> datetime | None:
        """将 SQLite 中保存的 ISO 文本转换为 Python datetime"""

        if value is None:
            return None
        
        return datetime.fromisoformat(value)


    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> Conversation:
        """将数据库行转换为 Conversation, 不在此处加载 Branch"""

        return Conversation(
            source_id=row["source_id"],
            title=row["title"],
            source_archive=row["source_archive"],
            source_entry=row["source_entry"],
            source_type=row["source_type"],
            id=row["id"],
            created_at=ConversationRepository._datetime_from_database(
                row["created_at"]
            ),
            updated_at=ConversationRepository._datetime_from_database(
                row["updated_at"]
            ),
            is_published=bool(row["is_published"]),
            import_batch=row["import_batch_id"],
        )


    def create(self, conversation: Conversation) -> int:
        """保存一个对话, 并返回数据库 ID"""

        cursor = self.connection.execute(
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
                self._datetime_to_database(conversation.created_at),
                self._datetime_to_database(conversation.updated_at),
                int(conversation.is_published),
                conversation.import_batch,
            ),
        )

        conversation.id = cursor.lastrowid

        if conversation.id is None:
            raise RuntimeError("保存对话后未获得数据库 ID")
        
        return conversation.id


    def get_by_id(self, conversation_id: int) -> Conversation | None:
        """根据数据库 ID 查询对话"""

        row = self.connection.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()

        if row is None:
            return None
        
        return self._row_to_conversation(row)


    def get_by_source_id(self, source_id: str) -> Conversation | None:
        """根据来源 ID 查询对话"""

        row = self.connection.execute(
            "SELECT * FROM conversations WHERE source_id = ?",
            (source_id,),
        ).fetchone()

        if row is None:
            return None
        
        return self._row_to_conversation(row)


    def update(self, conversation: Conversation) -> None:
        """更新一个对话"""

        if conversation.id is None:
            raise ValueError("更新对话前必须存在数据库 ID")

        self.connection.execute(
            """
            UPDATE conversations
            SET source_type = ?,
                source_id = ?,
                title = ?,
                source_archive = ?,
                source_entry = ?,
                created_at = ?,
                updated_at = ?,
                is_published = ?,
                import_batch_id = ?
            WHERE id = ?
            """,
            (
                conversation.source_type,
                conversation.source_id,
                conversation.title,
                conversation.source_archive,
                conversation.source_entry,
                self._datetime_to_database(conversation.created_at),
                self._datetime_to_database(conversation.updated_at),
                int(conversation.is_published),
                conversation.import_batch,
                conversation.id,
            ),
        )


    def list_published(self) -> list[Conversation]:
        """查询所有已发布的对话"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM conversations
            WHERE is_published = 1
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        
        conversations: list[Conversation] = []
        for row in rows:
            conversation = self._row_to_conversation(row)
            conversations.append(conversation)

        return conversations


@dataclass
class BranchRepository:
    """Branch 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _datetime_to_database(value: datetime | None) -> str | None:
        """将 Python datetime 转换为 SQLite 中保存的文本"""

        if value is None:
            return None

        return value.isoformat()


    @staticmethod
    def _datetime_from_database(value: str | None) -> datetime | None:
        """将 SQLite 中保存的 ISO 文本转换为 Python datetime"""

        if value is None:
            return None

        return datetime.fromisoformat(value)

    @staticmethod
    def _row_to_branch(row: sqlite3.Row) -> Branch:
        """将数据库行转换为 Branch, 不在此处加载 Message 和 Attachment"""

        branch = Branch(
            source_id=row["source_id"],
            index=row["branch_index"],
            fork_message_source_id=row["fork_message_source_id"],
            created_at=BranchRepository._datetime_from_database(
                row["created_at"]
            ),
            updated_at=BranchRepository._datetime_from_database(
                row["updated_at"]
            ),
            is_current=bool(row["is_current"]),
            id=row["id"],
            conversation_id=row["conversation_id"],
        )

        return branch

    def create(self, branch: Branch) -> int:
        """保存一个分支, 并返回数据库 ID"""

        if branch.conversation_id is None:
            raise ValueError("保存分支前必须存在 conversation_id")

        cursor = self.connection.execute(
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
                branch.conversation_id,
                branch.source_id,
                branch.index,
                branch.fork_message_source_id,
                self._datetime_to_database(branch.created_at),
                self._datetime_to_database(branch.updated_at),
                int(branch.is_current),
            ),
        )

        branch.id = cursor.lastrowid
        if branch.id is None:
            raise RuntimeError("保存分支后未获得数据库 ID")

        return branch.id


    def get_by_id(self, branch_id: int) -> Branch | None:
        """根据数据库 ID 查询分支"""

        row = self.connection.execute(
            "SELECT * FROM branches WHERE id = ?",
            (branch_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_branch(row)


    def get_by_source_id(self, source_id: str) -> Branch | None:
        """根据来源 ID 查询分支"""

        row = self.connection.execute(
            "SELECT * FROM branches WHERE source_id = ?",
            (source_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_branch(row)


    def list_by_conversation(self, conversation_id: int) -> list[Branch]:
        """查询某个对话下的所有分支"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM branches
            WHERE conversation_id = ?
            ORDER BY branch_index ASC, id ASC
            """,
            (conversation_id,),
        ).fetchall()

        branches: list[Branch] = []
        for row in rows:
            branch = self._row_to_branch(row)
            branches.append(branch)

        return branches


@dataclass
class MessageRepository:
    """Message 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _datetime_to_database(value: datetime | None) -> str | None:
        """将 Python datetime 转换为 SQLite 中保存的文本"""

        if value is None:
            return None

        return value.isoformat()


    @staticmethod
    def _datetime_from_database(value: str | None) -> datetime | None:
        """将 SQLite 中保存的 ISO 文本转换为 Python datetime"""

        if value is None:
            return None

        return datetime.fromisoformat(value)


    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        """将数据库行转换为 Message"""

        message = Message(
            source_id=row["source_id"],
            role=row["role"],
            content=row["content"],
            position=row["position"],
            thinking=row["thinking"],
            model=row["model"],
            timestamp=MessageRepository._datetime_from_database(
                row["timestamp"]
            ),
            id=row["id"],
            branch_id=row["branch_id"],
            edited_at=MessageRepository._datetime_from_database(
                row["edited_at"]
            ),
            edited_by=row["edited_by"],
        )

        return message


    def create(self, message: Message) -> int:
        """保存一条消息, 并返回数据库 ID"""

        if message.branch_id is None:
            raise ValueError("保存消息前必须存在 branch_id")

        cursor = self.connection.execute(
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
                message.branch_id,
                message.source_id,
                message.role,
                message.content,
                message.thinking,
                message.model,
                message.position,
                self._datetime_to_database(message.timestamp),
                self._datetime_to_database(message.edited_at),
                message.edited_by,
            ),
        )

        message.id = cursor.lastrowid
        if message.id is None:
            raise RuntimeError("保存消息后未获得数据库 ID")

        return message.id


    def get_by_id(self, message_id: int) -> Message | None:
        """根据数据库 ID 查询消息"""

        row = self.connection.execute(
            "SELECT * FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_message(row)


    def get_by_source_id(self, source_id: str) -> Message | None:
        """根据来源 ID 查询消息"""

        row = self.connection.execute(
            "SELECT * FROM messages WHERE source_id = ?",
            (source_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_message(row)


    def list_by_branch(self, branch_id: int) -> list[Message]:
        """按 position 顺序查询某个分支下的消息"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM messages
            WHERE branch_id = ?
            ORDER BY position ASC, id ASC
            """,
            (branch_id,),
        ).fetchall()

        messages: list[Message] = []
        for row in rows:
            message = self._row_to_message(row)
            messages.append(message)

        return messages


    def update(self, message: Message) -> None:
        """更新一条消息"""

        if message.id is None:
            raise ValueError("更新消息前必须存在数据库 ID")
        if message.branch_id is None:
            raise ValueError("更新消息前必须存在 branch_id")

        self.connection.execute(
            """
            UPDATE messages
            SET branch_id = ?,
                source_id = ?,
                role = ?,
                content = ?,
                thinking = ?,
                model = ?,
                position = ?,
                timestamp = ?,
                edited_at = ?,
                edited_by = ?
            WHERE id = ?
            """,
            (
                message.branch_id,
                message.source_id,
                message.role,
                message.content,
                message.thinking,
                message.model,
                message.position,
                self._datetime_to_database(message.timestamp),
                self._datetime_to_database(message.edited_at),
                message.edited_by,
                message.id,
            ),
        )


@dataclass
class AttachmentRepository:
    """Attachment 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _row_to_attachment(row: sqlite3.Row) -> Attachment:
        """将数据库行转换为 Attachment"""

        checksum_algorithm = row["checksum_algorithm"]
        checksum_value = row["checksum_value"]

        if checksum_algorithm is not None and checksum_value is not None:
            checksum = Checksum(
                algorithm = checksum_algorithm, 
                value = checksum_value
            )
        else:
            checksum = None    

        attachment = Attachment(
            message_source_id=row["message_source_id"],
            attach_type=row["attach_type"],
            source_ref=row["source_ref"],
            display_name=row["display_name"],
            mime_type=row["mime_type"],
            checksum=checksum,
            size=row["size"],
            id=row["id"],
            branch_id=row["branch_id"],
            message_id=row["message_id"],
        )

        return attachment


    def create(self, attachment: Attachment) -> int:
        """保存一个附件, 并返回数据库 ID"""

        if attachment.branch_id is None:
            raise ValueError("保存附件前必须存在 branch_id")
        if attachment.message_id is None:
            raise ValueError("保存附件前必须存在 message_id")

        checksum_algorithm = None
        checksum_value = None

        if attachment.checksum is not None:
            checksum_algorithm = attachment.checksum["algorithm"]
            checksum_value = attachment.checksum["value"]

        cursor = self.connection.execute(
            """
            INSERT INTO attachments (
                branch_id,
                message_id,
                message_source_id,
                attach_type,
                source_ref,
                display_name,
                mime_type,
                checksum_algorithm,
                checksum_value,
                size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attachment.branch_id,
                attachment.message_id,
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

        attachment.id = cursor.lastrowid
        if attachment.id is None:
            raise RuntimeError("保存附件后未获得数据库 ID")

        return attachment.id


    def get_by_id(self, attachment_id: int) -> Attachment | None:
        """根据数据库 ID 查询附件"""

        row = self.connection.execute(
            "SELECT * FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_attachment(row)


    def list_by_message(self, message_id: int) -> list[Attachment]:
        """查询某条消息下的所有附件"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM attachments
            WHERE message_id = ?
            ORDER BY id ASC
            """,
            (message_id,),
        ).fetchall()

        attachments: list[Attachment] = []
        for row in rows:
            attachment = self._row_to_attachment(row)
            attachments.append(attachment)

        return attachments


    def update(self, attachment: Attachment) -> None:
        """更新一个附件"""

        if attachment.id is None:
            raise ValueError("更新附件前必须存在数据库 ID")
        if attachment.branch_id is None:
            raise ValueError("更新附件前必须存在 branch_id")
        if attachment.message_id is None:
            raise ValueError("更新附件前必须存在 message_id")

        checksum_algorithm = None
        checksum_value = None

        if attachment.checksum is not None:
            checksum_algorithm = attachment.checksum["algorithm"]
            checksum_value = attachment.checksum["value"]

        self.connection.execute(
            """
            UPDATE attachments
            SET branch_id = ?,
                message_id = ?,
                message_source_id = ?,
                attach_type = ?,
                source_ref = ?,
                display_name = ?,
                mime_type = ?,
                checksum_algorithm = ?,
                checksum_value = ?,
                size = ?
            WHERE id = ?
            """,
            (
                attachment.branch_id,
                attachment.message_id,
                attachment.message_source_id,
                attachment.attach_type,
                attachment.source_ref,
                attachment.display_name,
                attachment.mime_type,
                checksum_algorithm,
                checksum_value,
                attachment.size,
                attachment.id,
            ),
        )


    def delete(self, attachment_id: int) -> None:
        """删除一个附件"""

        self.connection.execute(
            "DELETE FROM attachments WHERE id = ?",
            (attachment_id,),
        )


@dataclass
class UserRepository:
    """User 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _datetime_to_database(value: datetime) -> str:
        """将 Python datetime 转换为 SQLite 中保存的文本"""

        return value.isoformat()


    @staticmethod
    def _datetime_from_database(value: str) -> datetime:
        """将 SQLite 中保存的 ISO 文本转换为 Python datetime"""

        return datetime.fromisoformat(value)


    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        """将数据库行转换为 User"""

        user = User(
            username=row["username"],
            password_hash=row["password_hash"],
            created_at=UserRepository._datetime_from_database(row["created_at"]),
            id=row["id"],
            role=row["role"],
        )

        return user


    def create(self, user: User) -> int:
        """保存一个用户, 并返回数据库 ID"""

        cursor = self.connection.execute(
            """
            INSERT INTO users (
                username,
                password_hash,
                created_at,
                role
            ) VALUES (?, ?, ?, ?)
            """,
            (
                user.username,
                user.password_hash,
                self._datetime_to_database(user.created_at),
                user.role,
            ),
        )

        user.id = cursor.lastrowid
        if user.id is None:
            raise RuntimeError("保存用户后未获得数据库 ID")

        return user.id


    def get_by_id(self, user_id: int) -> User | None:
        """根据数据库 ID 查询用户"""

        row = self.connection.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_user(row)


    def get_by_username(self, username: str) -> User | None:
        """根据用户名查询用户"""

        row = self.connection.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_user(row)


    def update(self, user: User) -> None:
        """更新一个用户"""

        if user.id is None:
            raise ValueError("更新用户前必须存在数据库 ID")

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
                self._datetime_to_database(user.created_at),
                user.role,
                user.id,
            ),
        )


@dataclass
class CommentRepository:
    """Comment 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _datetime_to_database(value: datetime) -> str:
        """将 Python datetime 转换为 SQLite 中保存的文本"""

        return value.isoformat()


    @staticmethod
    def _datetime_from_database(value: str) -> datetime:
        """将 SQLite 中保存的 ISO 文本转换为 Python datetime"""

        return datetime.fromisoformat(value)


    @staticmethod
    def _row_to_comment(row: sqlite3.Row) -> Comment:
        """将数据库行转换为 Comment"""

        comment = Comment(
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
            target_type=row["target_type"],
            content=row["content"],
            created_at=CommentRepository._datetime_from_database(
                row["created_at"]
            ),
            created_by=row["created_by"],
            nickname=row["nickname"],
            is_deleted=bool(row["is_deleted"]),
        )

        return comment


    def create(self, comment: Comment) -> int:
        """保存一条评论, 并返回数据库 ID"""

        if comment.target_type == "conversation":
            if comment.conversation_id is None or comment.message_id is not None:
                raise ValueError("对话评论必须只设置 conversation_id")
        elif comment.target_type == "message":
            if comment.message_id is None or comment.conversation_id is not None:
                raise ValueError("消息评论必须只设置 message_id")
        else:
            raise ValueError("target_type 必须是 conversation 或 message")

        cursor = self.connection.execute(
            """
            INSERT INTO comments (
                conversation_id,
                message_id,
                target_type,
                content,
                created_at,
                created_by,
                nickname,
                is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                comment.conversation_id,
                comment.message_id,
                comment.target_type,
                comment.content,
                self._datetime_to_database(comment.created_at),
                comment.created_by,
                comment.nickname,
                int(comment.is_deleted),
            ),
        )

        return_id = cursor.lastrowid
        if return_id is None:
            raise RuntimeError("保存评论后未获得数据库 ID")

        return return_id


    def list_by_conversation(self, conversation_id: int) -> list[Comment]:
        """查询某个对话下的评论"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM comments
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        ).fetchall()

        comments: list[Comment] = []
        for row in rows:
            comment = self._row_to_comment(row)
            comments.append(comment)

        return comments


    def list_by_message(self, message_id: int) -> list[Comment]:
        """查询某条消息下的评论"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM comments
            WHERE message_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (message_id,),
        ).fetchall()

        comments: list[Comment] = []
        for row in rows:
            comment = self._row_to_comment(row)
            comments.append(comment)

        return comments


    def soft_delete(self, comment_id: int) -> None:
        """软删除一条评论"""

        self.connection.execute(
            "UPDATE comments SET is_deleted = 1 WHERE id = ?",
            (comment_id,),
        )


@dataclass
class AdminMarkRepository:
    """AdminMark 的持久化接口"""

    connection: sqlite3.Connection

    @staticmethod
    def _datetime_to_database(value: datetime) -> str:
        """将 Python datetime 转换为 SQLite 中保存的文本"""

        return value.isoformat()


    @staticmethod
    def _datetime_from_database(value: str) -> datetime:
        """将 SQLite 中保存的 ISO 文本转换为 Python datetime"""

        return datetime.fromisoformat(value)


    @staticmethod
    def _row_to_mark(row: sqlite3.Row) -> AdminMark:
        """将数据库行转换为 AdminMark"""

        mark = AdminMark(
            message_id=row["message_id"],
            mark_type=row["mark_type"],
            created_at=AdminMarkRepository._datetime_from_database(
                row["created_at"]
            ),
            created_by=row["created_by"],
            is_deleted=bool(row["is_deleted"]),
            id=row["id"],
        )

        return mark


    def create(self, mark: AdminMark) -> int:
        """保存一个管理员标记, 并返回数据库 ID"""

        cursor = self.connection.execute(
            """
            INSERT INTO admin_marks (
                message_id,
                mark_type,
                created_at,
                created_by,
                is_deleted
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                mark.message_id,
                mark.mark_type,
                self._datetime_to_database(mark.created_at),
                mark.created_by,
                int(mark.is_deleted),
            ),
        )

        mark.id = cursor.lastrowid
        if mark.id is None:
            raise RuntimeError("保存管理员标记后未获得数据库 ID")

        return mark.id


    def list_by_message(self, message_id: int) -> list[AdminMark]:
        """查询某条消息下的管理员标记"""

        rows = self.connection.execute(
            """
            SELECT *
            FROM admin_marks
            WHERE message_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (message_id,),
        ).fetchall()

        marks: list[AdminMark] = []
        for row in rows:
            mark = self._row_to_mark(row)
            marks.append(mark)

        return marks


    def soft_delete(self, mark_id: int) -> None:
        """软删除一个管理员标记"""
        
        self.connection.execute(
            "UPDATE admin_marks SET is_deleted = 1 WHERE id = ?",
            (mark_id,),
        )
