"""管理员初始化与对话级评论聚合的行为检查

覆盖两处新增能力:
- 用户服务的管理员注册与启动自检
- 评论服务按对话聚合直属评论与消息评论
"""

from pathlib import Path

import pytest

from bootstrap import ServiceContainer, ensure_initial_admin
from core.enums import CommentTarget, MessageRole, UserRole
from core.models import Branch, Conversation, Message
from modules.repositories import (
    BranchRepository,
    ConversationRepository,
    MessageRepository,
)


@pytest.fixture
def container(tmp_path: Path) -> ServiceContainer:
    service_container = ServiceContainer.create(
        database_path=tmp_path / "admin_comments.db",
        initialize=True,
    )
    yield service_container
    service_container.close()


def _seed_conversation(container: ServiceContainer) -> None:
    """写入一个对话, 一条分支和一条消息, 供评论挂载"""

    conversation_repository = ConversationRepository(container.connection)
    branch_repository = BranchRepository(container.connection)
    message_repository = MessageRepository(container.connection)

    conversation_repository.create(
        Conversation(source_id="conv-1", title="测试对话"),
    )
    branch_repository.create(
        Branch(source_id="conv-1::main", index=0),
        "conv-1",
    )
    message_repository.create(
        Message(
            source_id="msg-1",
            role=MessageRole.USER,
            content="你好",
            position=0,
        ),
        "conv-1::main",
    )


def test_register_creates_plain_user_and_register_admin_creates_admin(
    container: ServiceContainer,
) -> None:
    plain = container.user_service.register("alice", "pw-alice")
    admin = container.user_service.register_admin("root", "pw-root")

    assert plain.role == UserRole.USER
    assert admin.role == UserRole.ADMIN


def test_has_admin_reflects_database_state(container: ServiceContainer) -> None:
    assert container.user_service.has_admin() is False

    container.user_service.register("alice", "pw-alice")
    assert container.user_service.has_admin() is False

    container.user_service.register_admin("root", "pw-root")
    assert container.user_service.has_admin() is True


def test_ensure_initial_admin_skips_when_credentials_absent(
    container: ServiceContainer,
) -> None:
    assert ensure_initial_admin(container) is False
    assert ensure_initial_admin(container, username="root") is False
    assert ensure_initial_admin(container, password="pw-root") is False
    assert container.user_service.has_admin() is False


def test_ensure_initial_admin_creates_once_and_is_idempotent(
    container: ServiceContainer,
) -> None:
    assert ensure_initial_admin(container, "root", "pw-root") is True
    assert container.user_service.has_admin() is True

    assert ensure_initial_admin(container, "root", "pw-root") is False
    assert ensure_initial_admin(container, "other", "pw-other") is False

    assert container.user_service.get_by_username("other") is None


def test_ensure_initial_admin_rejects_taken_username(
    container: ServiceContainer,
) -> None:
    container.user_service.register("root", "pw-root")

    with pytest.raises(ValueError):
        ensure_initial_admin(container, "root", "pw-root")


def test_conversation_comment_query_includes_message_comments(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container)
    admin = container.user_service.register_admin("root", "pw-root")

    container.comment_service.create(
        admin,
        CommentTarget.CONVERSATION,
        "conv-1",
        "对话级评论",
    )
    container.comment_service.create(
        admin,
        CommentTarget.MESSAGE,
        "msg-1",
        "消息级评论",
    )

    direct = container.comment_service.list_by_conversation("conv-1")
    combined = container.comment_service.list_by_conversation_including_messages(
        "conv-1",
    )

    assert [comment.content for comment in direct] == ["对话级评论"]
    assert [comment.content for comment in combined] == ["对话级评论", "消息级评论"]


def test_conversation_comment_query_excludes_deleted_comments(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container)
    admin = container.user_service.register_admin("root", "pw-root")

    kept = container.comment_service.create(
        admin,
        CommentTarget.CONVERSATION,
        "conv-1",
        "保留",
    )
    removed = container.comment_service.create(
        admin,
        CommentTarget.MESSAGE,
        "msg-1",
        "删除",
    )
    container.comment_service.delete(admin, removed.id)

    combined = container.comment_service.list_by_conversation_including_messages(
        "conv-1",
    )

    assert [comment.id for comment in combined] == [kept.id]
    assert container.comment_service.list_by_message("msg-1") == []


def test_conversation_comment_query_ignores_other_conversations(
    container: ServiceContainer,
) -> None:
    _seed_conversation(container)
    admin = container.user_service.register_admin("root", "pw-root")

    container.comment_service.create(
        admin,
        CommentTarget.CONVERSATION,
        "conv-1",
        "属于 conv-1",
    )

    assert container.comment_service.list_by_conversation_including_messages(
        "conv-unknown",
    ) == []
