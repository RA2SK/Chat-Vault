"""仓储层的行为检查

这一层此前完全没有测试, 而它承担着三件容易被改坏的事:
- 内容图的父子关系靠 rowid 维持, 但对外只暴露 source_id, 预校验必须真的生效
- 分页的 LIMIT/OFFSET 与 has_more 的"多取一行"约定
- 批量查询返回的字典只包含有数据的键, 调用方必须用 get 取默认值

用例直接对着连接和仓储类写, 不经过服务层: 服务层有自己的测试, 这里要验证的
是 SQL 本身的行为, 引入服务层只会让失败原因变得难以定位.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import pytest

from core.enums import (
    AttachmentType,
    CommentTarget,
    ImportStatus,
    MarkType,
    MessageRole,
    SourceType,
    UserRole,
)
from core.exceptions import NotFoundError, ValidationError
from core.messages import MessageKey
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
from modules.repositories import (
    AdminMarkRepository,
    AttachmentRepository,
    BranchRepository,
    CommentRepository,
    ConversationRepository,
    ImportBatchRepository,
    MessageRepository,
    UserRepository,
)
from modules.repositories.database import (
    close_connection,
    get_connection,
    initialize_database,
)
from modules.repositories.mappings import _to_enum, _to_source_type
from modules.repositories.messages import _MAX_SQL_VARIABLES, _chunked

BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _at(minutes: int) -> datetime:
    """构造一个相对基准时间偏移若干分钟的时间戳"""

    return BASE_TIME + timedelta(minutes=minutes)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """一个已建好结构的独立数据库连接"""

    database_connection = get_connection(tmp_path / "repositories.db")
    initialize_database(database_connection)
    yield database_connection
    close_connection(database_connection)


def _seed_conversation(
    connection: sqlite3.Connection,
    source_id: str = "conv-1",
    *,
    title: str = "测试对话",
    updated_at: datetime | None = None,
    is_published: bool = False,
) -> Conversation:
    """写入一个对话并返回它"""

    conversation = Conversation(
        source_id=source_id,
        title=title,
        created_at=_at(0),
        updated_at=updated_at if updated_at is not None else _at(0),
        is_published=is_published,
    )
    ConversationRepository(connection).create(conversation)
    return conversation


def _seed_branch(
    connection: sqlite3.Connection,
    source_id: str = "conv-1::main",
    *,
    conversation_source_id: str = "conv-1",
    index: int = 0,
    is_current: bool = True,
) -> Branch:
    """写入一个分支并返回它"""

    branch = Branch(
        source_id=source_id,
        index=index,
        created_at=_at(0),
        updated_at=_at(0),
        is_current=is_current,
    )
    BranchRepository(connection).create(branch, conversation_source_id)
    return branch


def _seed_message(
    connection: sqlite3.Connection,
    source_id: str = "conv-1::main::msg-1",
    *,
    branch_source_id: str = "conv-1::main",
    position: int = 0,
    content: str = "你好",
    role: MessageRole = MessageRole.USER,
) -> Message:
    """写入一条消息并返回它"""

    message = Message(
        source_id=source_id,
        role=role,
        content=content,
        position=position,
        timestamp=_at(0),
    )
    MessageRepository(connection).create(message, branch_source_id)
    return message


def _seed_user(
    connection: sqlite3.Connection,
    username: str = "root",
    *,
    role: UserRole = UserRole.ADMIN,
) -> User:
    """写入一个用户并返回它"""

    user = User(
        username=username,
        password_hash="hash",
        created_at=_at(0),
        role=role,
    )
    UserRepository(connection).create(user)
    return user


# ---------------------------------------------------------------------------
# ConversationRepository
# ---------------------------------------------------------------------------


def test_conversation_roundtrip_preserves_every_field(
    connection: sqlite3.Connection,
) -> None:
    conversation = Conversation(
        source_id="conv-1",
        title="标题",
        source_archive="backup.zip",
        source_entry="sessions/1.json",
        source_type=SourceType.CHATBOX,
        created_at=_at(0),
        updated_at=_at(5),
        is_published=True,
    )
    repository = ConversationRepository(connection)
    repository.create(conversation)

    loaded = repository.get_by_source_id("conv-1")

    assert loaded is not None
    assert loaded.source_id == "conv-1"
    assert loaded.title == "标题"
    assert loaded.source_archive == "backup.zip"
    assert loaded.source_entry == "sessions/1.json"
    assert loaded.source_type == SourceType.CHATBOX
    assert loaded.created_at == _at(0)
    assert loaded.updated_at == _at(5)
    assert loaded.is_published is True


def test_conversation_get_by_source_id_returns_none_when_absent(
    connection: sqlite3.Connection,
) -> None:
    assert ConversationRepository(connection).get_by_source_id("nope") is None


def test_conversation_update_does_not_touch_timestamps(
    connection: sqlite3.Connection,
) -> None:
    """时间戳是备份内容的一部分, 不是写入时刻, update 不得顺手刷新"""

    repository = ConversationRepository(connection)
    _seed_conversation(connection)

    loaded = repository.get_by_source_id("conv-1")
    assert loaded is not None
    loaded.title = "改过的标题"
    loaded.created_at = _at(999)
    loaded.updated_at = _at(999)
    repository.update(loaded)

    reloaded = repository.get_by_source_id("conv-1")

    assert reloaded is not None
    assert reloaded.title == "改过的标题"
    assert reloaded.created_at == _at(0)
    assert reloaded.updated_at == _at(0)


def test_conversation_update_writes_the_editable_fields(
    connection: sqlite3.Connection,
) -> None:
    repository = ConversationRepository(connection)
    _seed_conversation(connection)

    loaded = repository.get_by_source_id("conv-1")
    assert loaded is not None
    loaded.source_type = SourceType.OTHER
    loaded.source_archive = "new.zip"
    loaded.source_entry = "new.json"
    loaded.is_published = True
    repository.update(loaded)

    reloaded = repository.get_by_source_id("conv-1")

    assert reloaded is not None
    assert reloaded.source_type == SourceType.OTHER
    assert reloaded.source_archive == "new.zip"
    assert reloaded.source_entry == "new.json"
    assert reloaded.is_published is True


def test_conversation_list_all_unbounded_returns_everything(
    connection: sqlite3.Connection,
) -> None:
    for index in range(3):
        _seed_conversation(
            connection,
            f"conv-{index}",
            updated_at=_at(index),
        )

    page = ConversationRepository(connection).list_all()

    assert [item.source_id for item in page.items] == ["conv-2", "conv-1", "conv-0"]
    assert page.has_more is False


def test_conversation_list_all_pages_with_has_more(
    connection: sqlite3.Connection,
) -> None:
    for index in range(3):
        _seed_conversation(
            connection,
            f"conv-{index}",
            updated_at=_at(index),
        )

    repository = ConversationRepository(connection)

    first = repository.list_all(limit=2)
    assert [item.source_id for item in first.items] == ["conv-2", "conv-1"]
    assert first.has_more is True

    second = repository.list_all(limit=2, offset=2)
    assert [item.source_id for item in second.items] == ["conv-0"]
    assert second.has_more is False

    third = repository.list_all(limit=2, offset=3)
    assert third.items == []
    assert third.has_more is False


def test_conversation_list_all_breaks_ties_by_id_descending(
    connection: sqlite3.Connection,
) -> None:
    """updated_at 相同时必须有一个确定的次序, 否则分页会漏行或重复行"""

    for index in range(3):
        _seed_conversation(connection, f"conv-{index}", updated_at=_at(0))

    page = ConversationRepository(connection).list_all()

    assert [item.source_id for item in page.items] == ["conv-2", "conv-1", "conv-0"]


def test_conversation_list_published_filters_and_pages(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection, "conv-0", updated_at=_at(0), is_published=True)
    _seed_conversation(connection, "conv-1", updated_at=_at(1), is_published=False)
    _seed_conversation(connection, "conv-2", updated_at=_at(2), is_published=True)

    repository = ConversationRepository(connection)

    assert [item.source_id for item in repository.list_published().items] == [
        "conv-2",
        "conv-0",
    ]

    first = repository.list_published(limit=1)
    assert [item.source_id for item in first.items] == ["conv-2"]
    assert first.has_more is True

    second = repository.list_published(limit=1, offset=1)
    assert [item.source_id for item in second.items] == ["conv-0"]
    assert second.has_more is False


# ---------------------------------------------------------------------------
# BranchRepository
# ---------------------------------------------------------------------------


def test_branch_create_rejects_missing_conversation(
    connection: sqlite3.Connection,
) -> None:
    """父节点不存在时立刻抛出可读错误, 而不是让外键约束在提交时报错"""

    with pytest.raises(NotFoundError) as excinfo:
        BranchRepository(connection).create(
            Branch(source_id="conv-1::main", index=0),
            "conv-1",
        )

    assert excinfo.value.key == MessageKey.CONVERSATION_BRANCH_ANCHOR_MISSING


def test_branch_roundtrip_preserves_every_field(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    branch = Branch(
        source_id="conv-1::fork",
        index=1,
        fork_message_source_id="conv-1::main::msg-1",
        created_at=_at(1),
        updated_at=_at(2),
        is_current=False,
    )
    repository = BranchRepository(connection)
    repository.create(branch, "conv-1")

    loaded = repository.get_by_source_id("conv-1::fork")

    assert loaded is not None
    assert loaded.source_id == "conv-1::fork"
    assert loaded.index == 1
    assert loaded.fork_message_source_id == "conv-1::main::msg-1"
    assert loaded.created_at == _at(1)
    assert loaded.updated_at == _at(2)
    assert loaded.is_current is False


def test_branch_get_by_source_id_returns_none_when_absent(
    connection: sqlite3.Connection,
) -> None:
    assert BranchRepository(connection).get_by_source_id("nope") is None


def test_branch_update_does_not_touch_timestamps(
    connection: sqlite3.Connection,
) -> None:
    repository = BranchRepository(connection)
    _seed_conversation(connection)
    _seed_branch(connection)

    loaded = repository.get_by_source_id("conv-1::main")
    assert loaded is not None
    loaded.index = 7
    loaded.created_at = _at(999)
    loaded.updated_at = _at(999)
    repository.update(loaded)

    reloaded = repository.get_by_source_id("conv-1::main")

    assert reloaded is not None
    assert reloaded.index == 7
    assert reloaded.created_at == _at(0)
    assert reloaded.updated_at == _at(0)


def test_branch_update_does_not_move_it_to_another_conversation(
    connection: sqlite3.Connection,
) -> None:
    """分支归属由首次导入决定, 迁移分支属于内容图重构, 不在重复导入范围内"""

    repository = BranchRepository(connection)
    _seed_conversation(connection, "conv-1")
    _seed_conversation(connection, "conv-2")
    _seed_branch(connection, "conv-1::main", conversation_source_id="conv-1")

    loaded = repository.get_by_source_id("conv-1::main")
    assert loaded is not None
    loaded.index = 3
    repository.update(loaded)

    assert [item.source_id for item in repository.list_by_conversation("conv-1")] == [
        "conv-1::main"
    ]
    assert repository.list_by_conversation("conv-2") == []


def test_branch_list_by_conversation_orders_by_index(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection, "conv-1::b", index=2)
    _seed_branch(connection, "conv-1::a", index=0)
    _seed_branch(connection, "conv-1::c", index=1)

    branches = BranchRepository(connection).list_by_conversation("conv-1")

    assert [branch.source_id for branch in branches] == [
        "conv-1::a",
        "conv-1::c",
        "conv-1::b",
    ]


def test_branch_list_by_conversation_returns_empty_for_unknown_conversation(
    connection: sqlite3.Connection,
) -> None:
    assert BranchRepository(connection).list_by_conversation("nope") == []


# ---------------------------------------------------------------------------
# MessageRepository
# ---------------------------------------------------------------------------


def test_message_create_rejects_missing_branch(
    connection: sqlite3.Connection,
) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        MessageRepository(connection).create(
            Message(
                source_id="msg-1",
                role=MessageRole.USER,
                content="你好",
                position=0,
            ),
            "conv-1::main",
        )

    assert excinfo.value.key == MessageKey.BRANCH_NOT_FOUND


def test_message_roundtrip_preserves_every_field(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    message = Message(
        source_id="msg-1",
        role=MessageRole.ASSISTANT,
        content="正文",
        position=3,
        thinking="思考",
        model="gpt-4",
        timestamp=_at(1),
        edited_at=_at(2),
    )
    repository = MessageRepository(connection)
    repository.create(message, "conv-1::main")

    loaded = repository.get_by_source_id("msg-1")

    assert loaded is not None
    assert loaded.source_id == "msg-1"
    assert loaded.role == MessageRole.ASSISTANT
    assert loaded.content == "正文"
    assert loaded.position == 3
    assert loaded.thinking == "思考"
    assert loaded.model == "gpt-4"
    assert loaded.timestamp == _at(1)
    assert loaded.edited_at == _at(2)
    assert loaded.edited_by is None


def test_message_get_by_source_id_returns_none_when_absent(
    connection: sqlite3.Connection,
) -> None:
    assert MessageRepository(connection).get_by_source_id("nope") is None


def test_message_get_conversation_source_id_walks_up_the_graph(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)

    repository = MessageRepository(connection)

    assert repository.get_conversation_source_id("conv-1::main::msg-1") == "conv-1"
    assert repository.get_conversation_source_id("nope") is None


def test_message_list_by_branch_orders_by_position(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection, "msg-b", position=2)
    _seed_message(connection, "msg-a", position=0)
    _seed_message(connection, "msg-c", position=1)

    page = MessageRepository(connection).list_by_branch("conv-1::main")

    assert [item.source_id for item in page.items] == ["msg-a", "msg-c", "msg-b"]
    assert page.has_more is False


def test_message_list_by_branch_pages_with_has_more(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    for index in range(3):
        _seed_message(connection, f"msg-{index}", position=index)

    repository = MessageRepository(connection)

    first = repository.list_by_branch("conv-1::main", limit=2)
    assert [item.source_id for item in first.items] == ["msg-0", "msg-1"]
    assert first.has_more is True

    second = repository.list_by_branch("conv-1::main", limit=2, offset=2)
    assert [item.source_id for item in second.items] == ["msg-2"]
    assert second.has_more is False


def test_message_list_by_branch_returns_empty_for_unknown_branch(
    connection: sqlite3.Connection,
) -> None:
    assert MessageRepository(connection).list_by_branch("nope").items == []


def test_message_list_by_branches_groups_and_omits_empty_branches(
    connection: sqlite3.Connection,
) -> None:
    """返回的字典只包含有消息的分支, 调用方必须用 get 取默认空列表"""

    _seed_conversation(connection)
    _seed_branch(connection, "conv-1::a", index=0)
    _seed_branch(connection, "conv-1::b", index=1)
    _seed_branch(connection, "conv-1::empty", index=2)
    _seed_message(connection, "msg-a1", branch_source_id="conv-1::a", position=0)
    _seed_message(connection, "msg-a2", branch_source_id="conv-1::a", position=1)
    _seed_message(connection, "msg-b1", branch_source_id="conv-1::b", position=0)

    grouped = MessageRepository(connection).list_by_branches(
        ["conv-1::a", "conv-1::b", "conv-1::empty"]
    )

    assert sorted(grouped) == ["conv-1::a", "conv-1::b"]
    assert [item.source_id for item in grouped["conv-1::a"]] == ["msg-a1", "msg-a2"]
    assert [item.source_id for item in grouped["conv-1::b"]] == ["msg-b1"]
    assert grouped.get("conv-1::empty", []) == []


def test_message_list_by_branches_returns_empty_dict_for_no_input(
    connection: sqlite3.Connection,
) -> None:
    assert MessageRepository(connection).list_by_branches([]) == {}


def test_message_update_writes_editable_fields_and_keeps_branch(
    connection: sqlite3.Connection,
) -> None:
    repository = MessageRepository(connection)
    _seed_conversation(connection)
    _seed_branch(connection, "conv-1::a", index=0)
    _seed_branch(connection, "conv-1::b", index=1)
    _seed_message(connection, "msg-1", branch_source_id="conv-1::a")

    loaded = repository.get_by_source_id("msg-1")
    assert loaded is not None
    loaded.content = "改过的正文"
    loaded.thinking = "改过的思考"
    loaded.model = "claude"
    loaded.role = MessageRole.SYSTEM
    loaded.edited_at = _at(9)
    repository.update(loaded)

    reloaded = repository.get_by_source_id("msg-1")

    assert reloaded is not None
    assert reloaded.content == "改过的正文"
    assert reloaded.thinking == "改过的思考"
    assert reloaded.model == "claude"
    assert reloaded.role == MessageRole.SYSTEM
    assert reloaded.edited_at == _at(9)
    assert repository.get_conversation_source_id("msg-1") == "conv-1"
    assert [item.source_id for item in repository.list_by_branch("conv-1::a").items] == [
        "msg-1"
    ]
    assert repository.list_by_branch("conv-1::b").items == []


def test_chunked_splits_into_fixed_size_batches() -> None:
    assert list(_chunked(["a", "b", "c"], 2)) == [["a", "b"], ["c"]]
    assert list(_chunked(["a", "b"], 2)) == [["a", "b"]]
    assert list(_chunked([], 2)) == []


def test_chunked_handles_more_values_than_the_sql_variable_limit() -> None:
    """参数个数超过 SQLite 变量上限时必须切分, 调用方不需要关心数量"""

    values = [f"v{index}" for index in range(_MAX_SQL_VARIABLES + 1)]

    chunks = list(_chunked(values, _MAX_SQL_VARIABLES))

    assert [len(chunk) for chunk in chunks] == [_MAX_SQL_VARIABLES, 1]
    assert [item for chunk in chunks for item in chunk] == values


# ---------------------------------------------------------------------------
# AttachmentRepository
# ---------------------------------------------------------------------------


def test_attachment_create_rejects_missing_message(
    connection: sqlite3.Connection,
) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        AttachmentRepository(connection).create(
            Attachment(
                message_source_id="msg-1",
                attach_type=AttachmentType.IMAGE,
                source_ref="resource/1.webp",
            )
        )

    assert excinfo.value.key == MessageKey.MESSAGE_ATTACHMENT_ANCHOR_MISSING


def test_attachment_roundtrip_preserves_every_field(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    attachment = Attachment(
        message_source_id="conv-1::main::msg-1",
        attach_type=AttachmentType.IMAGE,
        source_ref="resource/1.webp",
        display_name="图片",
        mime_type="image/webp",
        checksum=Checksum(algorithm="sha256", value="abc"),
        size=1024,
    )
    repository = AttachmentRepository(connection)
    repository.create(attachment)

    loaded = repository.list_by_message("conv-1::main::msg-1")

    assert len(loaded) == 1
    assert loaded[0].message_source_id == "conv-1::main::msg-1"
    assert loaded[0].attach_type == AttachmentType.IMAGE
    assert loaded[0].source_ref == "resource/1.webp"
    assert loaded[0].display_name == "图片"
    assert loaded[0].mime_type == "image/webp"
    assert loaded[0].checksum == Checksum(algorithm="sha256", value="abc")
    assert loaded[0].size == 1024


def test_attachment_checksum_is_none_when_either_column_is_null(
    connection: sqlite3.Connection,
) -> None:
    """两列必须同时存在才算有效校验值, 只有一半时视为没有"""

    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    repository = AttachmentRepository(connection)
    repository.create(
        Attachment(
            message_source_id="conv-1::main::msg-1",
            attach_type=AttachmentType.FILE,
            source_ref="resource/2.bin",
        )
    )

    loaded = repository.list_by_message("conv-1::main::msg-1")

    assert loaded[0].checksum is None
    assert loaded[0].size is None


def test_attachment_list_by_message_orders_by_insertion(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    repository = AttachmentRepository(connection)
    for name in ("a.webp", "b.webp", "c.webp"):
        repository.create(
            Attachment(
                message_source_id="conv-1::main::msg-1",
                attach_type=AttachmentType.IMAGE,
                source_ref=f"resource/{name}",
            )
        )

    loaded = repository.list_by_message("conv-1::main::msg-1")

    assert [item.source_ref for item in loaded] == [
        "resource/a.webp",
        "resource/b.webp",
        "resource/c.webp",
    ]


def test_attachment_list_by_message_returns_empty_for_unknown_message(
    connection: sqlite3.Connection,
) -> None:
    assert AttachmentRepository(connection).list_by_message("nope") == []


def test_attachment_list_by_messages_groups_and_omits_empty_messages(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection, "msg-a", position=0)
    _seed_message(connection, "msg-b", position=1)
    repository = AttachmentRepository(connection)
    repository.create(
        Attachment(
            message_source_id="msg-a",
            attach_type=AttachmentType.IMAGE,
            source_ref="resource/1.webp",
        )
    )
    repository.create(
        Attachment(
            message_source_id="msg-a",
            attach_type=AttachmentType.FILE,
            source_ref="resource/2.bin",
        )
    )

    grouped = repository.list_by_messages(["msg-a", "msg-b"])

    assert sorted(grouped) == ["msg-a"]
    assert [item.source_ref for item in grouped["msg-a"]] == [
        "resource/1.webp",
        "resource/2.bin",
    ]
    assert grouped.get("msg-b", []) == []


def test_attachment_update_does_not_change_identity(
    connection: sqlite3.Connection,
) -> None:
    """source_ref 与 message_source_id 是 WHERE 条件, 不是可编辑字段"""

    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    repository = AttachmentRepository(connection)
    repository.create(
        Attachment(
            message_source_id="conv-1::main::msg-1",
            attach_type=AttachmentType.IMAGE,
            source_ref="resource/1.webp",
        )
    )

    loaded = repository.list_by_message("conv-1::main::msg-1")[0]
    loaded.attach_type = AttachmentType.OTHER
    loaded.display_name = "改名了"
    loaded.mime_type = "application/octet-stream"
    loaded.checksum = Checksum(algorithm="md5", value="def")
    loaded.size = 42
    repository.update(loaded)

    reloaded = repository.list_by_message("conv-1::main::msg-1")

    assert len(reloaded) == 1
    assert reloaded[0].source_ref == "resource/1.webp"
    assert reloaded[0].message_source_id == "conv-1::main::msg-1"
    assert reloaded[0].attach_type == AttachmentType.OTHER
    assert reloaded[0].display_name == "改名了"
    assert reloaded[0].mime_type == "application/octet-stream"
    assert reloaded[0].checksum == Checksum(algorithm="md5", value="def")
    assert reloaded[0].size == 42


def test_attachment_delete_removes_only_the_named_row(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    repository = AttachmentRepository(connection)
    for name in ("a.webp", "b.webp"):
        repository.create(
            Attachment(
                message_source_id="conv-1::main::msg-1",
                attach_type=AttachmentType.IMAGE,
                source_ref=f"resource/{name}",
            )
        )

    repository.delete("conv-1::main::msg-1", "resource/a.webp")

    assert [item.source_ref for item in repository.list_by_message(
        "conv-1::main::msg-1"
    )] == ["resource/b.webp"]


def test_attachment_delete_is_silent_for_unknown_row(
    connection: sqlite3.Connection,
) -> None:
    """删除不存在的附件不报错, 重复导入时这是正常路径"""

    AttachmentRepository(connection).delete("nope", "nope")


# ---------------------------------------------------------------------------
# CommentRepository
# ---------------------------------------------------------------------------


def _comment(
    *,
    target_type: CommentTarget,
    conversation_source_id: str | None = None,
    message_source_id: str | None = None,
    content: str = "评论",
    created_at: datetime | None = None,
) -> Comment:
    """构造一条评论, 目标字段由调用方显式给出以便测试非法组合"""

    return Comment(
        target_type=target_type,
        content=content,
        created_at=created_at if created_at is not None else _at(0),
        conversation_source_id=conversation_source_id,
        message_source_id=message_source_id,
    )


def test_comment_create_requires_conversation_target(
    connection: sqlite3.Connection,
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CommentRepository(connection).create(
            _comment(target_type=CommentTarget.CONVERSATION)
        )

    assert excinfo.value.key == MessageKey.COMMENT_CONVERSATION_TARGET_REQUIRED


def test_comment_create_forbids_message_target_on_conversation_comment(
    connection: sqlite3.Connection,
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CommentRepository(connection).create(
            _comment(
                target_type=CommentTarget.CONVERSATION,
                conversation_source_id="conv-1",
                message_source_id="msg-1",
            )
        )

    assert excinfo.value.key == MessageKey.COMMENT_CONVERSATION_TARGET_FORBIDDEN


def test_comment_create_requires_message_target(
    connection: sqlite3.Connection,
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CommentRepository(connection).create(
            _comment(target_type=CommentTarget.MESSAGE)
        )

    assert excinfo.value.key == MessageKey.COMMENT_MESSAGE_TARGET_REQUIRED


def test_comment_create_forbids_conversation_target_on_message_comment(
    connection: sqlite3.Connection,
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CommentRepository(connection).create(
            _comment(
                target_type=CommentTarget.MESSAGE,
                conversation_source_id="conv-1",
                message_source_id="msg-1",
            )
        )

    assert excinfo.value.key == MessageKey.COMMENT_MESSAGE_TARGET_FORBIDDEN


def test_comment_create_rejects_unknown_target_type(
    connection: sqlite3.Connection,
) -> None:
    """目标类型不是枚举成员时必须在插入前拦下, 而不是让 CHECK 约束报错"""

    with pytest.raises(ValidationError) as excinfo:
        CommentRepository(connection).create(
            _comment(
                target_type="bogus",  # type: ignore[arg-type]
                conversation_source_id="conv-1",
            )
        )

    assert excinfo.value.key == MessageKey.COMMENT_TARGET_INVALID


def test_comment_list_by_conversation_excludes_message_comments(
    connection: sqlite3.Connection,
) -> None:
    """消息级评论的 conversation_source_id 为空, 因此不会被这条查询命中"""

    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    repository = CommentRepository(connection)
    repository.create(
        _comment(
            target_type=CommentTarget.CONVERSATION,
            conversation_source_id="conv-1",
            content="对话级",
        )
    )
    repository.create(
        _comment(
            target_type=CommentTarget.MESSAGE,
            message_source_id="conv-1::main::msg-1",
            content="消息级",
        )
    )

    direct = repository.list_by_conversation("conv-1")

    assert [comment.content for comment in direct] == ["对话级"]


def test_comment_list_by_conversation_excludes_deleted(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    repository = CommentRepository(connection)
    kept = _comment(
        target_type=CommentTarget.CONVERSATION,
        conversation_source_id="conv-1",
        content="保留",
    )
    removed = _comment(
        target_type=CommentTarget.CONVERSATION,
        conversation_source_id="conv-1",
        content="删除",
        created_at=_at(1),
    )
    repository.create(kept)
    repository.create(removed)
    repository.soft_delete(removed.id)

    assert [comment.id for comment in repository.list_by_conversation("conv-1")] == [
        kept.id
    ]


def test_comment_list_by_conversation_including_messages_merges_both_kinds(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    repository = CommentRepository(connection)
    repository.create(
        _comment(
            target_type=CommentTarget.CONVERSATION,
            conversation_source_id="conv-1",
            content="对话级",
            created_at=_at(0),
        )
    )
    repository.create(
        _comment(
            target_type=CommentTarget.MESSAGE,
            message_source_id="conv-1::main::msg-1",
            content="消息级",
            created_at=_at(1),
        )
    )

    page = repository.list_by_conversation_including_messages("conv-1")

    assert [comment.content for comment in page.items] == ["对话级", "消息级"]
    assert page.has_more is False


def test_comment_list_by_conversation_including_messages_pages(
    connection: sqlite3.Connection,
) -> None:
    """分页必须在 SQL 里完成, 否则第 N 页仍然要先取出全部评论"""

    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    repository = CommentRepository(connection)
    repository.create(
        _comment(
            target_type=CommentTarget.CONVERSATION,
            conversation_source_id="conv-1",
            content="对话级",
            created_at=_at(0),
        )
    )
    for index in range(2):
        repository.create(
            _comment(
                target_type=CommentTarget.MESSAGE,
                message_source_id="conv-1::main::msg-1",
                content=f"消息级{index}",
                created_at=_at(index + 1),
            )
        )

    first = repository.list_by_conversation_including_messages("conv-1", limit=2)
    assert [comment.content for comment in first.items] == ["对话级", "消息级0"]
    assert first.has_more is True

    second = repository.list_by_conversation_including_messages(
        "conv-1",
        limit=2,
        offset=2,
    )
    assert [comment.content for comment in second.items] == ["消息级1"]
    assert second.has_more is False


def test_comment_list_by_conversation_including_messages_ignores_other_conversations(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection, "conv-1")
    _seed_conversation(connection, "conv-2")
    _seed_branch(connection, "conv-2::main", conversation_source_id="conv-2")
    _seed_message(connection, "msg-2", branch_source_id="conv-2::main")
    repository = CommentRepository(connection)
    repository.create(
        _comment(
            target_type=CommentTarget.CONVERSATION,
            conversation_source_id="conv-2",
            content="属于 conv-2",
        )
    )
    repository.create(
        _comment(
            target_type=CommentTarget.MESSAGE,
            message_source_id="msg-2",
            content="也属于 conv-2",
        )
    )

    assert repository.list_by_conversation_including_messages("conv-1").items == []


def test_comment_list_by_message_returns_only_that_message(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection, "msg-a", position=0)
    _seed_message(connection, "msg-b", position=1)
    repository = CommentRepository(connection)
    repository.create(
        _comment(
            target_type=CommentTarget.MESSAGE,
            message_source_id="msg-a",
            content="给 a",
        )
    )
    repository.create(
        _comment(
            target_type=CommentTarget.MESSAGE,
            message_source_id="msg-b",
            content="给 b",
        )
    )

    assert [comment.content for comment in repository.list_by_message("msg-a")] == [
        "给 a"
    ]


def test_comment_soft_delete_reports_whether_a_row_changed(
    connection: sqlite3.Connection,
) -> None:
    """调用方需要区分"删掉了"和"这条评论根本不存在", 后者应当报 404"""

    _seed_conversation(connection)
    repository = CommentRepository(connection)
    comment = _comment(
        target_type=CommentTarget.CONVERSATION,
        conversation_source_id="conv-1",
    )
    repository.create(comment)

    assert repository.soft_delete(comment.id) is True
    assert repository.soft_delete(comment.id) is False
    assert repository.soft_delete("nope") is False


# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------


def test_user_roundtrip_by_id_and_username(
    connection: sqlite3.Connection,
) -> None:
    repository = UserRepository(connection)
    user = _seed_user(connection, "root", role=UserRole.ADMIN)

    by_id = repository.get_by_id(user.id)
    by_username = repository.get_by_username("root")

    assert by_id is not None
    assert by_id.username == "root"
    assert by_id.password_hash == "hash"
    assert by_id.created_at == _at(0)
    assert by_id.role == UserRole.ADMIN
    assert by_username is not None
    assert by_username.id == user.id


def test_user_lookups_return_none_when_absent(
    connection: sqlite3.Connection,
) -> None:
    repository = UserRepository(connection)

    assert repository.get_by_id("nope") is None
    assert repository.get_by_username("nope") is None


def test_user_has_role_answers_only_whether_any_exists(
    connection: sqlite3.Connection,
) -> None:
    """刻意只回答"有没有", 不提供"列出全部用户", 以免扩大用户信息暴露面"""

    repository = UserRepository(connection)

    assert repository.has_role(UserRole.ADMIN) is False
    assert repository.has_role(UserRole.USER) is False

    _seed_user(connection, "alice", role=UserRole.USER)

    assert repository.has_role(UserRole.USER) is True
    assert repository.has_role(UserRole.ADMIN) is False


def test_user_update_writes_role_and_password_hash(
    connection: sqlite3.Connection,
) -> None:
    repository = UserRepository(connection)
    user = _seed_user(connection, "alice", role=UserRole.USER)

    user.role = UserRole.ADMIN
    user.password_hash = "new-hash"
    repository.update(user)

    reloaded = repository.get_by_id(user.id)

    assert reloaded is not None
    assert reloaded.role == UserRole.ADMIN
    assert reloaded.password_hash == "new-hash"


# ---------------------------------------------------------------------------
# ImportBatchRepository
# ---------------------------------------------------------------------------


def _batch(
    *,
    file_name: str = "backup.zip",
    file_hash: str = "hash-1",
    started_at: datetime | None = None,
    status: ImportStatus = ImportStatus.SUCCESS,
) -> ImportBatch:
    """构造一个导入批次"""

    return ImportBatch(
        file_name=file_name,
        file_hash=file_hash,
        started_at=started_at if started_at is not None else _at(0),
        status=status,
        total_count=1,
        success_count=1,
        failed_count=0,
    )


def test_import_batch_roundtrip_preserves_every_field(
    connection: sqlite3.Connection,
) -> None:
    repository = ImportBatchRepository(connection)
    batch = ImportBatch(
        file_name="backup.zip",
        file_hash="hash-1",
        started_at=_at(0),
        finished_at=_at(1),
        status=ImportStatus.FAILED,
        total_count=3,
        success_count=1,
        failed_count=2,
        source_type=SourceType.CHATBOX,
        format_key="chatbox.v2",
        error_summary="警告: 有一条消息被跳过",
    )
    repository.create(batch)

    loaded = repository.get_by_id(batch.id)

    assert loaded is not None
    assert loaded.file_name == "backup.zip"
    assert loaded.file_hash == "hash-1"
    assert loaded.started_at == _at(0)
    assert loaded.finished_at == _at(1)
    assert loaded.status == ImportStatus.FAILED
    assert loaded.total_count == 3
    assert loaded.success_count == 1
    assert loaded.failed_count == 2
    assert loaded.source_type == SourceType.CHATBOX
    assert loaded.format_key == "chatbox.v2"
    assert loaded.error_summary == "警告: 有一条消息被跳过"


def test_import_batch_get_by_id_returns_none_when_absent(
    connection: sqlite3.Connection,
) -> None:
    assert ImportBatchRepository(connection).get_by_id("nope") is None


def test_import_batch_get_by_file_hash_returns_the_latest(
    connection: sqlite3.Connection,
) -> None:
    """同一份文件可能被导入多次, 摘要查询必须给出最近一次"""

    repository = ImportBatchRepository(connection)
    older = _batch(file_hash="hash-1", started_at=_at(0))
    newer = _batch(file_hash="hash-1", started_at=_at(5))
    repository.create(older)
    repository.create(newer)

    loaded = repository.get_by_file_hash("hash-1")

    assert loaded is not None
    assert loaded.id == newer.id


def test_import_batch_get_by_file_hash_returns_none_when_absent(
    connection: sqlite3.Connection,
) -> None:
    assert ImportBatchRepository(connection).get_by_file_hash("nope") is None


def test_import_batch_update_writes_final_counts_and_status(
    connection: sqlite3.Connection,
) -> None:
    repository = ImportBatchRepository(connection)
    batch = _batch(status=ImportStatus.SUCCESS)
    repository.create(batch)

    batch.status = ImportStatus.FAILED
    batch.finished_at = _at(3)
    batch.total_count = 2
    batch.success_count = 0
    batch.failed_count = 2
    batch.error_summary = "无法读取会话文件"
    repository.update(batch)

    reloaded = repository.get_by_id(batch.id)

    assert reloaded is not None
    assert reloaded.status == ImportStatus.FAILED
    assert reloaded.finished_at == _at(3)
    assert reloaded.total_count == 2
    assert reloaded.success_count == 0
    assert reloaded.failed_count == 2
    assert reloaded.error_summary == "无法读取会话文件"


# ---------------------------------------------------------------------------
# AdminMarkRepository
# ---------------------------------------------------------------------------


def test_admin_mark_roundtrip_and_deleted_filtering(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    user = _seed_user(connection)
    repository = AdminMarkRepository(connection)

    kept = AdminMark(
        message_source_id="conv-1::main::msg-1",
        mark_type=MarkType.HIGHLIGHT,
        created_at=_at(0),
        created_by=user.id,
    )
    removed = AdminMark(
        message_source_id="conv-1::main::msg-1",
        mark_type=MarkType.PIN,
        created_at=_at(1),
        created_by=user.id,
    )
    repository.create(kept)
    repository.create(removed)
    repository.soft_delete(removed.id)

    loaded = repository.list_by_message("conv-1::main::msg-1")

    assert [mark.id for mark in loaded] == [kept.id]
    assert loaded[0].mark_type == MarkType.HIGHLIGHT
    assert loaded[0].created_by == user.id
    assert loaded[0].is_deleted is False


def test_admin_mark_list_by_message_returns_empty_for_unknown_message(
    connection: sqlite3.Connection,
) -> None:
    assert AdminMarkRepository(connection).list_by_message("nope") == []


def test_admin_mark_soft_delete_reports_whether_a_row_changed(
    connection: sqlite3.Connection,
) -> None:
    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)
    user = _seed_user(connection)
    repository = AdminMarkRepository(connection)
    mark = AdminMark(
        message_source_id="conv-1::main::msg-1",
        mark_type=MarkType.OTHER,
        created_at=_at(0),
        created_by=user.id,
    )
    repository.create(mark)

    assert repository.soft_delete(mark.id) is True
    assert repository.soft_delete(mark.id) is False
    assert repository.soft_delete("nope") is False


# ---------------------------------------------------------------------------
# mappings
# ---------------------------------------------------------------------------


def test_to_enum_does_not_fall_back_on_an_illegal_value(
    connection: sqlite3.Connection,
) -> None:
    """有 CHECK 约束的列出现非法值说明库被外部改动过, 必须立刻暴露

    这里临时关掉 CHECK 约束来制造这种状态, 因为正常写入路径无法产生它.
    """

    _seed_conversation(connection)
    _seed_branch(connection)
    _seed_message(connection)

    connection.execute("PRAGMA ignore_check_constraints = ON")
    connection.execute(
        "UPDATE messages SET role = 'not-a-role' WHERE source_id = ?",
        ("conv-1::main::msg-1",),
    )

    with pytest.raises(ValueError):
        MessageRepository(connection).get_by_source_id("conv-1::main::msg-1")


def test_to_enum_accepts_a_legal_value() -> None:
    assert _to_enum(MessageRole, "assistant") == MessageRole.ASSISTANT


def test_to_source_type_falls_back_to_other() -> None:
    """source_type 没有 CHECK 约束, 认不出来就归入 other, 不让整行读不出来"""

    assert _to_source_type("chatbox") == SourceType.CHATBOX
    assert _to_source_type("something-new") == SourceType.OTHER


def test_conversation_with_unknown_source_type_is_still_readable(
    connection: sqlite3.Connection,
) -> None:
    """来源格式会随适配器增加, 旧版本写下的未知来源不能让查询失败"""

    _seed_conversation(connection)
    connection.execute(
        "UPDATE conversations SET source_type = 'future-format' WHERE source_id = ?",
        ("conv-1",),
    )

    loaded = ConversationRepository(connection).get_by_source_id("conv-1")

    assert loaded is not None
    assert loaded.source_type == SourceType.OTHER
