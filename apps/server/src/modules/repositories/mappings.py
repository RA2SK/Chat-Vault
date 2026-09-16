"""数据库行与核心模型之间的转换, 集中持有仓储层的列名知识

枚举列在写入时由 SQLite 存成文本, 读回来是裸字符串. 本模块负责把它们还原成
枚举成员, 否则模型字段的类型标注就是假的: 调用方拿到的是 ``str``, 一旦对它
调用 ``.value`` 或把它传给要求枚举的函数就会失败.

除 ``source_type`` 外, 所有枚举列在 schema 里都有 CHECK 约束, 库内取值必然
合法, 因此直接构造枚举即可. ``source_type`` 没有约束, 且来源格式会随适配器
增加, 所以它按"未知归入 other"处理, 避免一行无法识别的来源让整个查询失败.
"""

import sqlite3
from datetime import datetime
from enum import Enum
from typing import TypeVar

from core.enums import (
    AttachmentType,
    CommentTarget,
    ImportStatus,
    MarkType,
    MessageRole,
    SourceType,
    UserRole,
)
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

_EnumT = TypeVar("_EnumT", bound=Enum)


def _to_enum(enum_type: type[_EnumT], value: str) -> _EnumT:
    """把库内文本还原成枚举成员

    列上有 CHECK 约束时取值必然合法, 这里不做兜底: 真出现非法值说明库被外部
    改动过, 应当立刻暴露而不是被悄悄吞掉.
    """

    return enum_type(value)


def _to_source_type(value: str) -> SourceType:
    """把库内文本还原成 SourceType, 无法识别时归入 other

    ``conversations.source_type`` 与 ``import_batches.source_type`` 都没有 CHECK
    约束, 因为来源格式会随适配器增加. 这里与适配器侧的收敛规则保持一致:
    认不出来就是 other, 而不是让整行读不出来.
    """

    try:
        return SourceType(value)
    except ValueError:
        return SourceType.OTHER


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
        status=_to_enum(ImportStatus, row["status"]),
        total_count=row["total_count"],
        success_count=row["success_count"],
        failed_count=row["failed_count"],
        source_type=_to_source_type(row["source_type"]),
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
        source_type=_to_source_type(row["source_type"]),
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
        role=_to_enum(MessageRole, row["role"]),
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
        attach_type=_to_enum(AttachmentType, row["attach_type"]),
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
        role=_to_enum(UserRole, row["role"]),
        id=row["id"],
    )


def to_comment(row: sqlite3.Row) -> Comment:
    """将数据库行转换为 Comment"""

    return Comment(
        target_type=_to_enum(CommentTarget, row["target_type"]),
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
        mark_type=_to_enum(MarkType, row["mark_type"]),
        created_at=from_db_datetime(row["created_at"]),
        created_by=row["created_by"],
        is_deleted=bool(row["is_deleted"]),
        id=row["id"],
    )
