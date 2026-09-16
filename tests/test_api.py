"""HTTP 接口层的行为检查

覆盖四类此前没有验证过的边界:

- 错误响应的形状是否统一, 状态码是否由异常类型决定
- 未发布的对话是否既不出现在列表里, 也无法通过直接访问被区分出来
- 展示响应里是否真的不含备份组织, 导入批次和思考内容这些内部字段
- 管理接口在匿名身份下是否被服务层拒绝

测试通过 ``app.dependency_overrides`` 固定当前身份, 而不是伪造请求头:
请求头解析本身由 ``api/dependencies.py`` 负责, 这里要验证的是路由和服务层
的行为, 两者分开测才能定位问题出在哪一层.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_current_user
from bootstrap import ServiceContainer
from core.enums import CommentTarget, MarkType, MessageRole
from core.models import Branch, Conversation, Message
from modules.interfaces.users_intf import UserView
from modules.repositories import (
    BranchRepository,
    ConversationRepository,
    MessageRepository,
)
from modules.services.pagination import MAX_PAGE_SIZE

CONVERSATION_ID = "conv-1"
BRANCH_ID = "conv-1::main"
MESSAGE_ID = "conv-1::main::msg-1"


@pytest.fixture
def container(tmp_path: Path) -> Iterator[ServiceContainer]:
    service_container = ServiceContainer.create(
        database_path=tmp_path / "api.db",
        initialize=True,
    )
    yield service_container
    service_container.close()


@pytest.fixture
def app(container: ServiceContainer) -> Iterator[FastAPI]:
    """构造一个不经过 lifespan 的应用实例

    容器由测试直接放进 ``app.state``, 而不是让 lifespan 自己建: 测试需要
    控制数据库路径, 也需要在断言时直接读同一个容器.
    """

    from main import create_app

    application = create_app()
    application.state.container = container
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """构造一个不触发 lifespan 的测试客户端

    刻意不使用 ``with TestClient(app)``: 上下文管理器会执行应用的 lifespan,
    而 lifespan 会按默认数据库路径另建一个服务容器并覆盖 ``app.state.container``,
    测试自己放进去的容器随即被替换, 断言时读到的就不是同一个容器了.
    直接构造客户端不会触发 lifespan, 容器由测试独占.
    """

    yield TestClient(app)


def _seed_conversation(
    container: ServiceContainer,
    *,
    is_published: bool = False,
    thinking: str = "内部思考内容",
) -> None:
    """写入一个对话, 一条分支和一条消息"""

    conversation_repository = ConversationRepository(container.connection)
    branch_repository = BranchRepository(container.connection)
    message_repository = MessageRepository(container.connection)

    conversation_repository.create(
        Conversation(
            source_id=CONVERSATION_ID,
            title="测试对话",
            source_archive="backup.zip",
            is_published=is_published,
        ),
    )
    branch_repository.create(
        Branch(source_id=BRANCH_ID, index=0, is_current=True),
        CONVERSATION_ID,
    )
    message_repository.create(
        Message(
            source_id=MESSAGE_ID,
            role=MessageRole.USER,
            content="你好",
            position=0,
            thinking=thinking,
        ),
        BRANCH_ID,
    )


def _act_as(app: FastAPI, user: UserView | None) -> None:
    """把当前身份固定为给定用户"""

    app.dependency_overrides[get_current_user] = lambda: user


def _admin(container: ServiceContainer) -> UserView:
    return container.user_service.register_admin("root", "pw-root")


def _plain_user(container: ServiceContainer) -> UserView:
    return container.user_service.register("alice", "pw-alice")


def _items(response) -> list[dict]:
    """取出分页响应里的条目

    列表接口统一返回 ``{items, limit, offset, has_more}`` 信封而不是裸数组:
    裸数组没有地方放 ``has_more``, 前端只能靠"返回条数是否等于 limit"猜测还有
    没有下一页, 而最后一页刚好填满时这个判据是错的.
    """

    return response.json()["items"]


# === 错误响应形状 ===


def test_unknown_conversation_returns_error_envelope(client: TestClient) -> None:
    response = client.get("/api/conversations/conv-missing")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["key"] == "conversation_not_found"
    assert "conv-missing" in body["error"]["message"]


def test_comment_on_unknown_conversation_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.CONVERSATION.value,
            "target_source_id": "conv-missing",
            "content": "内容",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["key"] == "conversation_not_found"


def test_empty_comment_content_is_rejected_by_request_model(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.CONVERSATION.value,
            "target_source_id": CONVERSATION_ID,
            "content": "",
        },
    )

    assert response.status_code == 422


def test_login_failure_does_not_reveal_whether_user_exists(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _plain_user(container)

    unknown = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "pw"},
    )
    wrong_password = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong"},
    )

    assert unknown.status_code == 401
    assert wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()
    assert unknown.json()["error"]["key"] == "login_failed"


def test_login_success_returns_user_without_password_hash(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _plain_user(container)

    response = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "pw-alice"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "alice"
    assert body["role"] == "user"
    assert "password_hash" not in body


# === 发布状态与可见性 ===


def test_unpublished_conversation_is_absent_from_list(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=False)

    response = client.get("/api/conversations")

    assert response.status_code == 200
    assert _items(response) == []


def test_unpublished_conversation_is_indistinguishable_from_missing(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=False)

    hidden = client.get(f"/api/conversations/{CONVERSATION_ID}")
    missing = client.get("/api/conversations/conv-missing")

    assert hidden.status_code == 404
    assert missing.status_code == 404
    assert hidden.json()["error"]["key"] == missing.json()["error"]["key"]


def test_admin_sees_unpublished_conversation(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=False)
    _act_as(app, _admin(container))

    listed = client.get("/api/conversations")
    detail = client.get(f"/api/conversations/{CONVERSATION_ID}")

    assert [item["source_id"] for item in _items(listed)] == [CONVERSATION_ID]
    assert detail.status_code == 200


def test_published_conversation_is_visible_anonymously(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=True)

    listed = client.get("/api/conversations")
    detail = client.get(f"/api/conversations/{CONVERSATION_ID}")

    assert [item["source_id"] for item in _items(listed)] == [CONVERSATION_ID]
    assert detail.status_code == 200


# === 展示响应不含内部字段 ===


def test_display_responses_strip_internal_fields(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=True)

    summary = _items(client.get("/api/conversations"))[0]
    detail = client.get(f"/api/conversations/{CONVERSATION_ID}").json()
    message = detail["messages"][0]

    for payload in (summary, detail, message):
        assert "source_archive" not in payload
        assert "source_entry" not in payload
        assert "import_batch_id" not in payload

    assert "thinking" not in message
    assert message["content"] == "你好"


def test_publish_response_strips_internal_fields(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=False)
    _act_as(app, _admin(container))

    response = client.post(f"/api/admin/conversations/{CONVERSATION_ID}/publish")

    assert response.status_code == 200
    body = response.json()
    assert body["source_id"] == CONVERSATION_ID
    assert "source_archive" not in body
    assert "import_batch_id" not in body


# === 权限由服务层执行 ===


def test_anonymous_cannot_publish(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=False)

    response = client.post(f"/api/admin/conversations/{CONVERSATION_ID}/publish")

    assert response.status_code == 403
    assert response.json()["error"]["key"] == "admin_required"


def test_plain_user_cannot_publish(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=False)
    _act_as(app, _plain_user(container))

    response = client.post(f"/api/admin/conversations/{CONVERSATION_ID}/publish")

    assert response.status_code == 403


def test_anonymous_cannot_create_comment(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=True)

    response = client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.CONVERSATION.value,
            "target_source_id": CONVERSATION_ID,
            "content": "匿名评论",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["key"] == "comment_create_forbidden"


def test_unknown_acting_user_is_rejected(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=True)

    response = client.get(
        "/api/conversations",
        headers={"X-Chat-Vault-User": "nobody"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["key"] == "authentication_required"


def test_acting_user_header_resolves_real_user(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _seed_conversation(container, is_published=False)
    _admin(container)

    response = client.get(
        "/api/conversations",
        headers={"X-Chat-Vault-User": "root"},
    )

    assert response.status_code == 200
    assert [item["source_id"] for item in _items(response)] == [CONVERSATION_ID]


# === 评论 ===


def test_comment_round_trip(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=True)
    _act_as(app, _plain_user(container))

    created = client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.CONVERSATION.value,
            "target_source_id": CONVERSATION_ID,
            "content": "第一条评论",
            "nickname": "访客",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["content"] == "第一条评论"
    assert body["nickname"] == "访客"
    assert "created_by" not in body

    listed = client.get(f"/api/conversations/{CONVERSATION_ID}/comments")
    assert [item["id"] for item in _items(listed)] == [body["id"]]


def test_conversation_comments_include_message_comments(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=True)
    _act_as(app, _plain_user(container))

    client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.CONVERSATION.value,
            "target_source_id": CONVERSATION_ID,
            "content": "对话级",
        },
    )
    client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.MESSAGE.value,
            "target_source_id": MESSAGE_ID,
            "content": "消息级",
        },
    )

    listed = client.get(f"/api/conversations/{CONVERSATION_ID}/comments")

    assert [item["content"] for item in _items(listed)] == ["对话级", "消息级"]


def test_comments_of_unpublished_conversation_are_not_readable(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=False)
    _act_as(app, _admin(container))

    client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.CONVERSATION.value,
            "target_source_id": CONVERSATION_ID,
            "content": "内部讨论",
        },
    )

    _act_as(app, None)
    response = client.get(f"/api/conversations/{CONVERSATION_ID}/comments")

    assert response.status_code == 404


def test_admin_can_delete_comment(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=True)
    _act_as(app, _admin(container))

    created = client.post(
        "/api/comments",
        json={
            "target_type": CommentTarget.CONVERSATION.value,
            "target_source_id": CONVERSATION_ID,
            "content": "待删除",
        },
    ).json()

    removed = client.delete(f"/api/comments/{created['id']}")
    listed = client.get(f"/api/conversations/{CONVERSATION_ID}/comments")

    assert removed.status_code == 204
    assert _items(listed) == []


# === 管理员标记 ===


def test_mark_round_trip(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=True)
    _act_as(app, _admin(container))

    created = client.post(
        f"/api/admin/messages/{MESSAGE_ID}/marks",
        json={"mark_type": MarkType.HIGHLIGHT.value},
    )

    assert created.status_code == 201
    body = created.json()
    assert body["message_source_id"] == MESSAGE_ID
    assert body["mark_type"] == MarkType.HIGHLIGHT.value
    assert "created_by" not in body

    removed = client.delete(f"/api/admin/marks/{body['id']}")
    assert removed.status_code == 204


def test_mark_on_unknown_message_returns_404(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _act_as(app, _admin(container))

    response = client.post(
        "/api/admin/messages/msg-missing/marks",
        json={"mark_type": MarkType.PIN.value},
    )

    assert response.status_code == 404
    assert response.json()["error"]["key"] == "message_not_found"


def test_marks_are_readable_after_creation(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    """标记创建后必须能读回来, 否则前端只能写不能显示"""

    _seed_conversation(container, is_published=True)
    _act_as(app, _admin(container))

    created = client.post(
        f"/api/admin/messages/{MESSAGE_ID}/marks",
        json={"mark_type": MarkType.HIGHLIGHT.value},
    )
    assert created.status_code == 201

    listed = client.get(f"/api/admin/messages/{MESSAGE_ID}/marks")

    assert listed.status_code == 200
    assert [mark["id"] for mark in listed.json()] == [created.json()["id"]]


def test_deleted_mark_disappears_from_listing(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    _seed_conversation(container, is_published=True)
    _act_as(app, _admin(container))

    created = client.post(
        f"/api/admin/messages/{MESSAGE_ID}/marks",
        json={"mark_type": MarkType.PIN.value},
    )
    assert client.delete(f"/api/admin/marks/{created.json()['id']}").status_code == 204

    listed = client.get(f"/api/admin/messages/{MESSAGE_ID}/marks")

    assert listed.status_code == 200
    assert listed.json() == []


def test_anonymous_cannot_list_marks(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """标记属于管理侧数据, 匿名读取必须被拒绝"""

    _seed_conversation(container, is_published=True)

    response = client.get(f"/api/admin/messages/{MESSAGE_ID}/marks")

    assert response.status_code == 403
    assert response.json()["error"]["key"] == "admin_required"


# === 管理员注册 ===


def test_admin_registration_creates_admin(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    response = client.post(
        "/api/admin/users",
        json={"username": "root", "password": "pw-root"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    assert container.user_service.has_admin() is True


def test_admin_registration_rejects_duplicate_username(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    _admin(container)

    response = client.post(
        "/api/admin/users",
        json={"username": "root", "password": "pw-root"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["key"] == "username_already_exists"


# === 导入 ===


def test_import_missing_file_returns_422(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
    tmp_path: Path,
) -> None:
    _act_as(app, _admin(container))

    response = client.post(
        "/api/admin/imports",
        json={"path": str(tmp_path / "missing.zip")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["key"] == "import_file_not_found"


def test_import_unknown_format_key_returns_422(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
    tmp_path: Path,
) -> None:
    _act_as(app, _admin(container))
    backup = tmp_path / "backup.zip"
    backup.write_text("not a real backup", encoding="utf-8")

    response = client.post(
        "/api/admin/imports",
        json={"path": str(backup), "format_key": "unknown.format"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["key"] == "import_format_mismatch"


def test_import_unrecognized_file_returns_422(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
    tmp_path: Path,
) -> None:
    _act_as(app, _admin(container))
    backup = tmp_path / "backup.zip"
    backup.write_text("not a real backup", encoding="utf-8")

    response = client.post(
        "/api/admin/imports",
        json={"path": str(backup)},
    )

    assert response.status_code == 422
    assert response.json()["error"]["key"] == "import_format_mismatch"


# === 分页 ===


def _seed_many_conversations(
    container: ServiceContainer,
    count: int,
    *,
    is_published: bool = True,
) -> list[str]:
    """写入多个对话, 返回按列表顺序排列的来源 ID

    列表按 ``updated_at DESC, id DESC`` 排序, 而这里写入的时间戳完全相同,
    因此实际顺序由 id 决定. 断言时按 id 倒序排列, 与排序键保持一致.
    """

    conversation_repository = ConversationRepository(container.connection)

    source_ids = [f"conv-{index:03d}" for index in range(count)]

    for source_id in source_ids:
        conversation_repository.create(
            Conversation(
                source_id=source_id,
                title=f"对话 {source_id}",
                source_archive="backup.zip",
                is_published=is_published,
            ),
        )

    return sorted(source_ids, reverse=True)


def test_conversation_list_reports_has_more(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """一页装不下时 has_more 为真, 装得下时为假

    这是信封存在的理由: 裸数组只能靠"返回条数是否等于 limit"猜测, 而最后一页
    刚好填满时那个判据是错的.
    """

    _seed_many_conversations(container, 3)

    first = client.get("/api/conversations", params={"limit": 2})

    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["has_more"] is True

    second = client.get("/api/conversations", params={"limit": 2, "offset": 2})

    assert second.status_code == 200
    body = second.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False


def test_conversation_list_pages_do_not_overlap(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """逐页取完的结果与一次取完的结果一致, 且没有重复或遗漏"""

    expected = _seed_many_conversations(container, 5)

    collected: list[str] = []
    offset = 0

    while True:
        response = client.get(
            "/api/conversations",
            params={"limit": 2, "offset": offset},
        )
        body = response.json()
        collected.extend(item["source_id"] for item in body["items"])

        if not body["has_more"]:
            break

        offset += len(body["items"])

    assert collected == expected


def test_offset_past_the_end_returns_empty_page(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """偏移超出总数时返回空页而不是报错

    翻页过程中数据被删掉就会出现这种情况, 报错会让前端卡在错误状态上,
    返回空页则让前端自然地停下来.
    """

    _seed_many_conversations(container, 2)

    response = client.get("/api/conversations", params={"offset": 100})

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["has_more"] is False


def test_limit_above_maximum_is_clamped(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """超过上限的 limit 被收敛到上限, 而不是被拒绝

    "要得太多"是意图而不是错误, 因此收敛; 而 limit 小于 1 是无效参数,
    由查询参数校验直接拒绝.
    """

    _seed_many_conversations(container, 2)

    response = client.get("/api/conversations", params={"limit": 100000})

    assert response.status_code == 200
    assert response.json()["limit"] == MAX_PAGE_SIZE


def test_invalid_limit_is_rejected_with_error_envelope(
    client: TestClient,
) -> None:
    """limit 小于 1 时返回与业务异常同形状的错误信封

    FastAPI 自带的校验失败响应是 ``{"detail": [...]}``, 与业务异常的
    ``{"error": {...}}`` 不同. 前端如果只按一种形状解析, 就会在参数写错时
    拿到一个解析不了的结构, 因此这里把它翻译成同一种形状.
    """

    response = client.get("/api/conversations", params={"limit": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["key"] == "request_invalid"
    assert "limit" in body["error"]["message"]


def test_negative_offset_is_rejected(client: TestClient) -> None:
    """负偏移是无效参数"""

    response = client.get("/api/conversations", params={"offset": -1})

    assert response.status_code == 422
    assert response.json()["error"]["key"] == "request_invalid"


def test_comment_list_is_paginated(
    client: TestClient,
    container: ServiceContainer,
    app: FastAPI,
) -> None:
    """评论列表同样按页返回"""

    _seed_conversation(container, is_published=True)
    _act_as(app, _plain_user(container))

    for index in range(3):
        client.post(
            "/api/comments",
            json={
                "target_type": CommentTarget.CONVERSATION.value,
                "target_source_id": CONVERSATION_ID,
                "content": f"评论 {index}",
            },
        )

    first = client.get(
        f"/api/conversations/{CONVERSATION_ID}/comments",
        params={"limit": 2},
    )

    assert first.status_code == 200
    body = first.json()
    assert [item["content"] for item in body["items"]] == ["评论 0", "评论 1"]
    assert body["has_more"] is True

    second = client.get(
        f"/api/conversations/{CONVERSATION_ID}/comments",
        params={"limit": 2, "offset": 2},
    )

    assert [item["content"] for item in second.json()["items"]] == ["评论 2"]
    assert second.json()["has_more"] is False


# === 消息分页接口 ===


def test_message_list_returns_current_branch_messages(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """不指定分支时返回当前链的消息"""

    _seed_conversation(container, is_published=True)

    response = client.get(f"/api/conversations/{CONVERSATION_ID}/messages")

    assert response.status_code == 200
    body = response.json()
    assert [item["source_id"] for item in body["items"]] == [MESSAGE_ID]
    assert body["has_more"] is False


def test_message_list_accepts_explicit_branch(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """指定分支时返回该分支的消息"""

    _seed_conversation(container, is_published=True)

    response = client.get(
        f"/api/conversations/{CONVERSATION_ID}/messages",
        params={"branch_source_id": BRANCH_ID},
    )

    assert response.status_code == 200
    assert [item["source_id"] for item in response.json()["items"]] == [MESSAGE_ID]


def test_message_list_rejects_branch_of_another_conversation(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """分支不属于该对话时返回 404

    返回空列表会让调用方以为"这个分支没有消息", 而实际原因是分支根本不属于
    这个对话. 状态码与"对话不存在"保持一致, 避免借此探测未发布对话的分支结构.
    """

    _seed_conversation(container, is_published=True)

    response = client.get(
        f"/api/conversations/{CONVERSATION_ID}/messages",
        params={"branch_source_id": "conv-other::main"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["key"] == "conversation_not_found"


def test_message_list_of_unpublished_conversation_is_not_readable(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """未发布的对话对匿名调用方不可读"""

    _seed_conversation(container, is_published=False)

    response = client.get(f"/api/conversations/{CONVERSATION_ID}/messages")

    assert response.status_code == 404


def test_message_list_strips_internal_fields(
    client: TestClient,
    container: ServiceContainer,
) -> None:
    """消息分页响应同样不含思考内容等内部字段"""

    _seed_conversation(container, is_published=True)

    message = client.get(f"/api/conversations/{CONVERSATION_ID}/messages").json()[
        "items"
    ][0]

    assert "thinking" not in message
    assert message["content"] == "你好"
