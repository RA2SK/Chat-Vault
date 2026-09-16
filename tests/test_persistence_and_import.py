"""持久化边界, 重复导入与管理员标记的行为检查

覆盖四类此前缺失的行为:
- 服务层写操作是否真的落库(A1 事务边界)
- 重复导入是否保住管理员对消息做的编辑(A2)
- 分支更新是否真的写回数据库(A3)
- 已删除的管理员标记是否被过滤(C1), 重复导入是否被识别(C7)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterator

import pytest

from bootstrap import ServiceContainer
from core.enums import MarkType, MessageRole
from core.models import Attachment, Branch, Conversation, Message
from modules.interfaces.importing_intf import ParseResult
from modules.repositories import BranchRepository, MessageRepository

MAIN_BRANCH = "conv-1::main"
FIRST_MESSAGE = "conv-1::main::msg-1"


@pytest.fixture
def container(tmp_path: Path) -> Iterator[ServiceContainer]:
    service_container = ServiceContainer.create(
        database_path=tmp_path / "persistence.db",
        initialize=True,
    )
    yield service_container
    service_container.close()


def _write_backup(workspace: Path, name: str, content: str) -> Path:
    """写一个内容可控的假备份文件, 只用于提供文件摘要"""

    path = workspace / name
    path.write_text(content, encoding="utf-8")
    return path


@dataclass
class _FakeParse:
    """把固定对话图包成一次解析调用, 避免依赖真实的压缩包解析"""

    conversation: Conversation

    def results(self) -> Iterator[ParseResult]:
        yield ParseResult(
            conversation=self.conversation,
            source_id=self.conversation.source_id,
        )


def _build_conversation(
    *,
    branch_index: int = 0,
    is_current: bool = True,
    message_content: str = "原始内容",
) -> Conversation:
    """构造一个只含一条分支, 一条消息和一个附件的对话图"""

    message = Message(
        source_id=FIRST_MESSAGE,
        role=MessageRole.USER,
        content=message_content,
        position=0,
    )
    message.attachments.append(
        Attachment(
            message_source_id=message.source_id,
            attach_type="image",
            source_ref="resource/1.webp",
        )
    )

    return Conversation(
        source_id="conv-1",
        title="测试对话",
        branches=[
            Branch(
                source_id=MAIN_BRANCH,
                index=branch_index,
                is_current=is_current,
                messages=[message],
            )
        ],
    )


def _import(
    container: ServiceContainer,
    workspace: Path,
    file_name: str,
    file_content: str,
    conversation: Conversation,
) -> None:
    """走一次完整的导入, 文件内容与对话图分开控制"""

    container.import_service.import_results(
        path=_write_backup(workspace, file_name, file_content),
        results=_FakeParse(conversation).results(),
        format_key="fake.v1",
    )


def test_service_write_survives_reopen(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """服务层的写操作必须真的落库, 而不是停在未提交的事务里"""

    container.user_service.register_admin("root", "pw-root")
    container.close()

    reopened = ServiceContainer.create(
        database_path=tmp_path / "persistence.db",
        initialize=False,
    )
    try:
        assert reopened.user_service.get_by_username("root") is not None
    finally:
        reopened.close()


def test_reimport_preserves_message_edits(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """重复导入不能把消息内容回退到原始版本"""

    admin = container.user_service.register_admin("root", "pw-root")
    _import(container, tmp_path, "a.zip", "first", _build_conversation())

    message_repository = MessageRepository(container.connection)
    stored = message_repository.get_by_source_id(FIRST_MESSAGE)
    assert stored is not None
    stored.content = "EDITED"
    stored.edited_at = datetime.now(timezone.utc)
    stored.edited_by = admin.id
    message_repository.update(stored)

    _import(
        container,
        tmp_path,
        "b.zip",
        "second",
        _build_conversation(message_content="重新解析出的内容"),
    )

    reloaded = message_repository.get_by_source_id(FIRST_MESSAGE)
    assert reloaded is not None
    assert reloaded.content == "EDITED"
    assert reloaded.edited_at is not None


def test_reimport_keeps_unedited_message_in_sync(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """没有被编辑过的消息仍然允许按新的解析结果覆盖"""

    _import(container, tmp_path, "a.zip", "first", _build_conversation())

    _import(
        container,
        tmp_path,
        "b.zip",
        "second",
        _build_conversation(message_content="重新解析出的内容"),
    )

    message_repository = MessageRepository(container.connection)
    reloaded = message_repository.get_by_source_id(FIRST_MESSAGE)
    assert reloaded is not None
    assert reloaded.content == "重新解析出的内容"


def test_reimport_updates_branch_but_keeps_is_current(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """分支更新必须写回数据库, 同时不覆盖由管理侧控制的 is_current"""

    _import(container, tmp_path, "a.zip", "first", _build_conversation())

    branch_repository = BranchRepository(container.connection)
    branch_repository.connection.execute(
        "UPDATE branches SET is_current = 0 WHERE source_id = ?",
        (MAIN_BRANCH,),
    )
    branch_repository.connection.commit()

    _import(
        container,
        tmp_path,
        "b.zip",
        "second",
        _build_conversation(branch_index=7, is_current=True),
    )

    reloaded = branch_repository.get_by_source_id(MAIN_BRANCH)
    assert reloaded is not None
    assert reloaded.index == 7
    assert reloaded.is_current is False


def test_duplicate_import_is_reported_and_skipped(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """同一份文件内容重复导入时返回原批次, 不产生新批次"""

    path = _write_backup(tmp_path, "a.zip", "same-bytes")
    first = container.import_service.import_results(
        path=path,
        results=_FakeParse(_build_conversation()).results(),
        format_key="fake.v1",
    )

    file_hash = sha256(path.read_bytes()).hexdigest()
    duplicate = container.import_service.find_duplicate_import(file_hash)
    assert duplicate is not None
    assert duplicate.id == first.id

    second = container.import_service.import_results(
        path=path,
        results=_FakeParse(_build_conversation()).results(),
        format_key="fake.v1",
    )
    assert second.id == first.id

    total = container.connection.execute(
        "SELECT COUNT(*) FROM import_batches"
    ).fetchone()[0]
    assert total == 1


def test_list_marks_excludes_deleted_marks(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """软删除的管理员标记不再出现在查询结果里"""

    admin = container.user_service.register_admin("root", "pw-root")
    _import(container, tmp_path, "a.zip", "first", _build_conversation())

    kept = container.moderation_service.add_mark(admin, FIRST_MESSAGE, MarkType.HIGHLIGHT)
    removed = container.moderation_service.add_mark(admin, FIRST_MESSAGE, MarkType.PIN)
    container.moderation_service.remove_mark(admin, removed.id)

    marks = container.moderation_service.list_marks(FIRST_MESSAGE)
    assert [mark.id for mark in marks] == [kept.id]


def test_mark_requires_admin(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """普通用户不能添加管理员标记"""

    _import(container, tmp_path, "a.zip", "first", _build_conversation())
    plain_user = container.user_service.register("alice", "pw-alice")

    with pytest.raises(PermissionError):
        container.moderation_service.add_mark(plain_user, FIRST_MESSAGE, MarkType.PIN)
