"""契约边界字段剥离的行为检查

覆盖三类此前"声明了但没有真正执行"的剥离承诺:
- 用户服务的任何返回值是否都不含 password_hash, 改密是否只接受视图
- 发布服务是否真的产出展示视图而不是原始领域模型
- 展示视图是否摈弃思考内容, 备份组织和导入批次等内部字段

这些用例针对的是"实现是否真的做到了契约声明的事", 而不是契约的形状,
契约的形状由 tests/test_interface_contracts.py 和 pyright 负责.
"""

from dataclasses import asdict, fields
from pathlib import Path
from typing import Iterator

import pytest

from bootstrap import ServiceContainer
from core.enums import AttachmentType, MessageRole
from core.models import Attachment, Branch, Conversation, Message
from core.pagination import Page
from modules.interfaces.publishing_intf import (
    PublishedConversationSummary,
    PublishedConversationView,
)
from modules.interfaces.users_intf import UserView
from modules.repositories import (
    AttachmentRepository,
    BranchRepository,
    ConversationRepository,
    MessageRepository,
)
from modules.services.pagination import MAX_PAGE_SIZE

CONVERSATION = "conv-1"
MAIN_BRANCH = "conv-1::main"
FORK_BRANCH = "conv-1::fork"
FIRST_MESSAGE = "conv-1::msg-1"
FORK_MESSAGE = "conv-1::fork::msg-1"

# 这些字段属于持久化或管理侧信息, 不允许出现在展示输出里
INTERNAL_CONVERSATION_FIELDS = {
    "source_archive",
    "source_entry",
    "source_type",
    "is_published",
    "import_batch_id",
    "branches",
}
INTERNAL_MESSAGE_FIELDS = {"thinking", "edited_by"}


@pytest.fixture
def container(tmp_path: Path) -> Iterator[ServiceContainer]:
    service_container = ServiceContainer.create(
        database_path=tmp_path / "boundary.db",
        initialize=True,
    )
    yield service_container
    service_container.close()


def _seed_conversation(
    container: ServiceContainer,
    *,
    is_published: bool = False,
) -> None:
    """写入一个带主链和分支的对话, 并给主链消息挂一个附件"""

    conversation_repository = ConversationRepository(container.connection)
    branch_repository = BranchRepository(container.connection)
    message_repository = MessageRepository(container.connection)
    attachment_repository = AttachmentRepository(container.connection)

    conversation_repository.create(
        Conversation(
            source_id=CONVERSATION,
            title="展示用对话",
            source_archive="backup.zip",
            source_entry="vault/chatbox.json",
            is_published=is_published,
        ),
    )
    branch_repository.create(
        Branch(source_id=MAIN_BRANCH, index=0, is_current=True),
        CONVERSATION,
    )
    branch_repository.create(
        Branch(source_id=FORK_BRANCH, index=1),
        CONVERSATION,
    )
    message_repository.create(
        Message(
            source_id=FIRST_MESSAGE,
            role=MessageRole.USER,
            content="主链问题",
            position=0,
            thinking="主链思考内容",
        ),
        MAIN_BRANCH,
    )
    message_repository.create(
        Message(
            source_id=FORK_MESSAGE,
            role=MessageRole.ASSISTANT,
            content="分支回答",
            position=0,
            thinking="分支思考内容",
        ),
        FORK_BRANCH,
    )
    attachment_repository.create(
        Attachment(
            message_source_id=FIRST_MESSAGE,
            attach_type=AttachmentType.IMAGE,
            source_ref="images/a.png",
        ),
    )


def test_user_service_never_returns_password_hash(
    container: ServiceContainer,
) -> None:
    plain = container.user_service.register("alice", "pw-alice")
    admin = container.user_service.register_admin("root", "pw-root")

    returned = [
        plain,
        admin,
        container.user_service.authenticate("alice", "pw-alice"),
        container.user_service.get(plain.id),
        container.user_service.get_by_username("alice"),
    ]

    for user in returned:
        assert user is not None
        assert isinstance(user, UserView)
        assert "password_hash" not in asdict(user)
        assert "password_hash" not in {field.name for field in fields(user)}


def test_user_view_stays_in_sync_with_user_model(
    container: ServiceContainer,
) -> None:
    """User 新增字段时这条用例会提醒维护者考虑是否要暴露它"""

    container.user_service.register("alice", "pw-alice")
    user = container.user_service.get_by_username("alice")

    assert user is not None
    assert set(asdict(user)) == {"id", "username", "role", "created_at"}


def test_change_password_accepts_only_a_view(container: ServiceContainer) -> None:
    container.user_service.register("alice", "pw-old")

    user = container.user_service.authenticate("alice", "pw-old")

    assert user is not None
    assert isinstance(user, UserView)

    container.user_service.change_password(user, "pw-old", "pw-new")

    assert container.user_service.authenticate("alice", "pw-old") is None
    assert container.user_service.authenticate("alice", "pw-new") is not None


def test_change_password_rejects_wrong_old_password(
    container: ServiceContainer,
) -> None:
    user = container.user_service.register("alice", "pw-old")

    with pytest.raises(PermissionError):
        container.user_service.change_password(user, "pw-wrong", "pw-new")

    assert container.user_service.authenticate("alice", "pw-old") is not None


def test_change_password_rejects_empty_new_password(
    container: ServiceContainer,
) -> None:
    user = container.user_service.register("alice", "pw-old")

    with pytest.raises(ValueError):
        container.user_service.change_password(user, "pw-old", "")

    assert container.user_service.authenticate("alice", "pw-old") is not None


def test_change_password_rejects_missing_user(
    container: ServiceContainer,
) -> None:
    user = container.user_service.register("alice", "pw-old")
    container.connection.execute("DELETE FROM users WHERE id = ?", (user.id,))
    container.connection.commit()

    with pytest.raises(LookupError):
        container.user_service.change_password(user, "pw-old", "pw-new")


def test_list_for_view_returns_summaries_without_internal_fields(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container)
    admin = container.user_service.register_admin("root", "pw-root")

    summaries = container.publishing_service.list_for_view(
        admin,
        Page(limit=MAX_PAGE_SIZE),
    ).items

    assert len(summaries) == 1
    summary = summaries[0]
    assert isinstance(summary, PublishedConversationSummary)
    assert summary.source_id == CONVERSATION
    assert summary.title == "展示用对话"
    assert INTERNAL_CONVERSATION_FIELDS.isdisjoint(asdict(summary))


def test_get_conversation_for_view_strips_internal_fields(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container)
    admin = container.user_service.register_admin("root", "pw-root")

    view = container.publishing_service.get_conversation_for_view(admin, CONVERSATION)

    assert view is not None
    assert isinstance(view, PublishedConversationView)
    assert INTERNAL_CONVERSATION_FIELDS.isdisjoint(asdict(view))

    assert view.messages
    for message in view.messages:
        assert INTERNAL_MESSAGE_FIELDS.isdisjoint(asdict(message))


def test_published_view_flattens_only_the_current_branch(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container)
    admin = container.user_service.register_admin("root", "pw-root")

    view = container.publishing_service.get_conversation_for_view(admin, CONVERSATION)

    assert view is not None
    assert [message.content for message in view.messages] == ["主链问题"]
    assert [message.source_id for message in view.messages] == [FIRST_MESSAGE]


def test_published_messages_carry_attachment_refs(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container)
    admin = container.user_service.register_admin("root", "pw-root")

    view = container.publishing_service.get_conversation_for_view(admin, CONVERSATION)

    assert view is not None
    assert view.messages[0].attachments == ["images/a.png"]


def test_unpublished_conversation_is_invisible_to_plain_user(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=False)
    plain = container.user_service.register("alice", "pw-alice")

    # 存在但未发布, 与不存在返回同一个结果, 调用方无法借此枚举未发布对话
    assert (
        container.publishing_service.get_conversation_for_view(plain, CONVERSATION)
        is None
    )
    assert (
        container.publishing_service.get_conversation_for_view(plain, "conv-missing")
        is None
    )
    assert (
        container.publishing_service.list_for_view(
            plain,
            Page(limit=MAX_PAGE_SIZE),
        ).items
        == []
    )


def test_published_conversation_is_visible_to_plain_user(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=True)
    plain = container.user_service.register("alice", "pw-alice")

    view = container.publishing_service.get_conversation_for_view(plain, CONVERSATION)

    assert view is not None
    assert [
        summary.source_id
        for summary in container.publishing_service.list_for_view(
            plain,
            Page(limit=MAX_PAGE_SIZE),
        ).items
    ] == [
        CONVERSATION,
    ]
