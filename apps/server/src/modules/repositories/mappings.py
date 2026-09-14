"""数据库行与核心模型之间的转换, 集中持有仓储层的列名知识"""

import sqlite3
from datetime import datetime

from core.models import (
    AdminMark,
    Attachment,
    Branch,
    Comment,
    Conversation,
    ImportBatch,
    Message,
    User,
)
from core.types import Checksum


def to_db_datetime(value: datetime | None) -> str | None:
    """将 Python datetime 转换为 SQLite 中保存的 ISO 文本"""

    if value is None:
        return None

    return value.isoformat()


def from_db_datetime(value: str) -> datetime:
    """将 SQLite 中保存的 ISO 文本转换为 Python datetime, 用于 NOT NULL 列"""

    return datetime.fromisoformat(value)


def from_db_datetime_optional(value: str | None) -> datetime | None:
    """将 SQLite 中保存的 ISO 文本转换为 Python datetime, 用于可空列"""

    if value is None:
        return None

    return datetime.fromisoformat(value)


def to_db_checksum(checksum: Checksum | None) -> tuple[str | None, str | None]:
    """将模型的校验值拆成 checksum_algorithm 与 checksum_value 两列"""

    if checksum is None:
        return None, None

    return checksum["algorithm"], checksum["value"]


def from_db_checksum(row: sqlite3.Row) -> Checksum | None:
    """从数据库行还原校验值, 两列必须同时存在才视为有效"""

    algorithm = row["checksum_algorithm"]
    value = row["checksum_value"]

    if algorithm is None or value is None:
        return None

    return Checksum(algorithm=algorithm, value=value)


def to_import_batch(row: sqlite3.Row) -> ImportBatch:
    """将数据库行转换为 ImportBatch"""

    return ImportBatch(
        file_name=row["file_name"],
        file_hash=row["file_hash"],
        started_at=from_db_datetime(row["started_at"]),
        status=row["status"],
        total_count=row["total_count"],
        success_count=row["success_count"],
        failed_count=row["failed_count"],
        source_type=row["source_type"],
        format_key=row["format_key"],
        error_summary=row["error_summary"],
        finished_at=from_db_datetime_optional(row["finished_at"]),
        id=row["id"],
    )


def to_conversation(row: sqlite3.Row) -> Conversation:
    """将数据库行转换为 Conversation, 不在此处加载 Branch"""

    return Conversation(
        source_id=row["source_id"],
        title=row["title"],
        source_archive=row["source_archive"],
        source_entry=row["source_entry"],
        source_type=row["source_type"],
        created_at=from_db_datetime_optional(row["created_at"]),
        updated_at=from_db_datetime_optional(row["updated_at"]),
        is_published=bool(row["is_published"]),
        import_batch_id=row["import_batch_id"],
    )


def to_branch(row: sqlite3.Row) -> Branch:
    """将数据库行转换为 Branch, 不在此处加载 Message 和 Attachment"""

    return Branch(
        source_id=row["source_id"],
        index=row["branch_index"],
        fork_message_source_id=row["fork_message_source_id"],
        created_at=from_db_datetime_optional(row["created_at"]),
        updated_at=from_db_datetime_optional(row["updated_at"]),
        is_current=bool(row["is_current"]),
    )


def to_message(row: sqlite3.Row) -> Message:
    """将数据库行转换为 Message"""

    return Message(
        source_id=row["source_id"],
        role=row["role"],
        content=row["content"],
        position=row["position"],
        thinking=row["thinking"],
        model=row["model"],
        timestamp=from_db_datetime_optional(row["timestamp"]),
        edited_at=from_db_datetime_optional(row["edited_at"]),
        edited_by=row["edited_by"],
    )


def to_attachment(row: sqlite3.Row) -> Attachment:
    """将数据库行转换为 Attachment"""

    return Attachment(
        message_source_id=row["message_source_id"],
        attach_type=row["attach_type"],
        source_ref=row["source_ref"],
        display_name=row["display_name"],
        mime_type=row["mime_type"],
        checksum=from_db_checksum(row),
        size=row["size"],
    )


def to_user(row: sqlite3.Row) -> User:
    """将数据库行转换为 User"""

    return User(
        username=row["username"],
        password_hash=row["password_hash"],
        created_at=from_db_datetime(row["created_at"]),
        role=row["role"],
        id=row["id"],
    )


def to_comment(row: sqlite3.Row) -> Comment:
    """将数据库行转换为 Comment"""

    return Comment(
        target_type=row["target_type"],
        content=row["content"],
        created_at=from_db_datetime(row["created_at"]),
        conversation_source_id=row["conversation_source_id"],
        message_source_id=row["message_source_id"],
        created_by=row["created_by"],
        nickname=row["nickname"],
        id=row["id"],
        is_deleted=bool(row["is_deleted"]),
    )


def to_admin_mark(row: sqlite3.Row) -> AdminMark:
    """将数据库行转换为 AdminMark"""

    return AdminMark(
        message_source_id=row["message_source_id"],
        mark_type=row["mark_type"],
        created_at=from_db_datetime(row["created_at"]),
        created_by=row["created_by"],
        is_deleted=bool(row["is_deleted"]),
        id=row["id"],
    )
