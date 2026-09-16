"""Chatbox v2 备份适配器的行为检查

这个适配器是唯一把外部备份翻译成核心内容模型的地方, 也是全项目最大的单个
模块, 此前完全没有测试. 它同时承担三件事:
- 格式识别: 认错格式会让别的适配器拿到不属于自己的文件
- 容错解析: 备份里任何一处结构异常都只能降级成警告或单条错误, 不能让整次导入崩掉
- 安全校验: 图片资源的路径来自外部文件, 必须挡住绝对路径和目录穿越

用例通过真实构造 zip 来驱动解析, 而不是直接调用私有方法: 私有方法的输入
形状由 parse 决定, 绕过 parse 就等于绕过了真正需要验证的那一层.
"""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from core.enums import AttachmentType, MessageRole, SourceType
from modules.adapters.chatbox_v2 import ChatboxV2Importer
from modules.interfaces.importing_intf import ParseResult

MANIFEST_NAME = "manifest.json"


def _manifest(
    sessions: Any,
    *,
    resources: Any = None,
    fmt: Any = "chatbox-backup",
    format_version: Any = 2,
    application: Any = None,
) -> dict[str, Any]:
    """构造一份 manifest.json 的内容"""

    manifest: dict[str, Any] = {
        "format": fmt,
        "formatVersion": format_version,
        "application": (
            {"name": "Chatbox"} if application is None else application
        ),
        "sessions": sessions,
    }
    if resources is not None:
        manifest["resources"] = resources
    return manifest


def _session(
    session_id: str,
    *,
    name: Any = "测试会话",
    messages: Any = None,
    threads: Any = None,
    message_forks_hash: Any = None,
) -> dict[str, Any]:
    """构造一份会话文件的内容"""

    session: dict[str, Any] = {
        "id": session_id,
        "name": name,
        "messages": [] if messages is None else messages,
    }
    if threads is not None:
        session["threads"] = threads
    if message_forks_hash is not None:
        session["messageForksHash"] = message_forks_hash
    return session


def _message(
    message_id: str,
    *,
    role: Any = "user",
    parts: Any = None,
    timestamp: Any = 1700000000000,
    **extra: Any,
) -> dict[str, Any]:
    """构造一条消息"""

    message: dict[str, Any] = {
        "id": message_id,
        "role": role,
        "contentParts": [{"type": "text", "text": "正文"}] if parts is None else parts,
        "timestamp": timestamp,
    }
    message.update(extra)
    return message


def _build_backup(
    workspace: Path,
    *,
    manifest: Any,
    sessions: dict[str, Any] | None = None,
    extra_files: dict[str, bytes] | None = None,
    name: str = "backup.zip",
) -> Path:
    """把 manifest, 会话文件和资源文件打包成一个真实的 zip

    manifest 允许传入非字典, 用于验证"顶层结构不是对象"这条错误路径.
    """

    path = workspace / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False),
        )
        for entry_name, content in (sessions or {}).items():
            archive.writestr(entry_name, json.dumps(content, ensure_ascii=False))
        for entry_name, content in (extra_files or {}).items():
            archive.writestr(entry_name, content)
    return path


def _single_session_backup(
    workspace: Path,
    *,
    session_id: str = "session-1",
    session: dict[str, Any] | None = None,
    resources: Any = None,
    extra_files: dict[str, bytes] | None = None,
    name: str = "backup.zip",
) -> Path:
    """构造一个只含一个会话的备份, 覆盖绝大多数用例"""

    session_path = f"sessions/{session_id}.json"
    return _build_backup(
        workspace,
        manifest=_manifest(
            [{"id": session_id, "path": session_path}],
            resources=resources,
        ),
        sessions={
            session_path: (
                _session(session_id) if session is None else session
            )
        },
        extra_files=extra_files,
        name=name,
    )


def _parse(path: Path) -> list[ParseResult]:
    """跑一次解析并把迭代器取成列表"""

    return list(ChatboxV2Importer().parse(path))


def _only(path: Path) -> ParseResult:
    """解析一个只应产出一条结果的备份"""

    results = _parse(path)
    assert len(results) == 1
    return results[0]


@pytest.fixture
def importer() -> ChatboxV2Importer:
    return ChatboxV2Importer()


# ---------------------------------------------------------------------------
# 适配器身份
# ---------------------------------------------------------------------------


def test_importer_declares_its_identity(importer: ChatboxV2Importer) -> None:
    """format_key 是适配器的身份, source_type 决定 source_id 的命名空间前缀"""

    assert importer.format_key == "chatbox.v2"
    assert importer.source_type == SourceType.CHATBOX
    assert importer.empty_thinking_markers == {"", "[redacted]"}


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------


def test_detect_accepts_a_well_formed_backup(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = _single_session_backup(tmp_path)

    assert importer.detect(path) is True


def test_detect_rejects_a_file_that_is_not_a_zip(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = tmp_path / "plain.json"
    path.write_text("{}", encoding="utf-8")

    assert importer.detect(path) is False


def test_detect_rejects_a_zip_without_manifest(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sessions/1.json", "{}")

    assert importer.detect(path) is False


def test_detect_rejects_a_manifest_that_is_not_an_object(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = _build_backup(tmp_path, manifest=["not", "an", "object"])

    assert importer.detect(path) is False


def test_detect_rejects_a_manifest_without_application(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = _build_backup(
        tmp_path,
        manifest={
            "format": "chatbox-backup",
            "formatVersion": 2,
            "sessions": [],
        },
    )

    assert importer.detect(path) is False


def test_detect_rejects_a_manifest_whose_application_is_not_an_object(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = _build_backup(
        tmp_path,
        manifest=_manifest([], application="Chatbox"),
    )

    assert importer.detect(path) is False


@pytest.mark.parametrize(
    ("fmt", "format_version", "application"),
    [
        ("other-backup", 2, {"name": "Chatbox"}),
        ("chatbox-backup", 1, {"name": "Chatbox"}),
        ("chatbox-backup", 2, {"name": "OtherApp"}),
    ],
)
def test_detect_rejects_a_manifest_with_the_wrong_identity(
    importer: ChatboxV2Importer,
    tmp_path: Path,
    fmt: Any,
    format_version: Any,
    application: Any,
) -> None:
    """三个身份字段必须同时匹配, 否则文件属于别的适配器"""

    path = _build_backup(
        tmp_path,
        manifest=_manifest(
            [],
            fmt=fmt,
            format_version=format_version,
            application=application,
        ),
    )

    assert importer.detect(path) is False


def test_detect_rejects_a_manifest_that_is_not_valid_json(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = tmp_path / "broken.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(MANIFEST_NAME, "{ not json")

    assert importer.detect(path) is False


def test_detect_rejects_a_manifest_that_is_not_utf8(
    importer: ChatboxV2Importer,
    tmp_path: Path,
) -> None:
    path = tmp_path / "bad-encoding.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(MANIFEST_NAME, b"\xff\xfe\x00\x00")

    assert importer.detect(path) is False


# ---------------------------------------------------------------------------
# parse: manifest 层错误
# ---------------------------------------------------------------------------


def test_parse_reports_a_manifest_that_is_not_an_object(tmp_path: Path) -> None:
    path = _build_backup(tmp_path, manifest="not-an-object")

    result = _only(path)

    assert result.error == "会话索引项顶层结构不是有效的 JSON 对象"
    assert result.source_ref == MANIFEST_NAME
    assert result.conversation is None


def test_parse_reports_a_missing_sessions_list(tmp_path: Path) -> None:
    path = _build_backup(
        tmp_path,
        manifest={
            "format": "chatbox-backup",
            "formatVersion": 2,
            "application": {"name": "Chatbox"},
        },
    )

    result = _only(path)

    assert result.error == "会话索引项中缺少有效的 sessions 列表"
    assert result.source_ref == MANIFEST_NAME


def test_parse_reports_a_session_entry_that_is_not_an_object(
    tmp_path: Path,
) -> None:
    path = _build_backup(tmp_path, manifest=_manifest(["not-an-object"]))

    result = _only(path)

    assert result.error == "会话索引项不是有效对象"
    assert result.source_ref == MANIFEST_NAME


@pytest.mark.parametrize("bad_id", [None, "", 123])
def test_parse_reports_a_session_entry_without_a_valid_id(
    tmp_path: Path,
    bad_id: Any,
) -> None:
    path = _build_backup(
        tmp_path,
        manifest=_manifest([{"id": bad_id, "path": "sessions/1.json"}]),
    )

    result = _only(path)

    assert result.error == "会话索引项缺少有效的 id"


@pytest.mark.parametrize("bad_path", [None, "", 123])
def test_parse_reports_a_session_entry_without_a_valid_path(
    tmp_path: Path,
    bad_path: Any,
) -> None:
    path = _build_backup(
        tmp_path,
        manifest=_manifest([{"id": "session-1", "path": bad_path}]),
    )

    result = _only(path)

    assert result.error == "会话索引项缺少有效的 path"


def test_parse_reports_an_unreadable_session_file(tmp_path: Path) -> None:
    """索引里写了路径但压缩包里没有这个文件"""

    path = _build_backup(
        tmp_path,
        manifest=_manifest([{"id": "session-1", "path": "sessions/missing.json"}]),
    )

    result = _only(path)

    assert result.error is not None
    assert result.error.startswith("无法读取会话文件: ")
    assert result.source_id == "session-1"
    assert result.source_ref == "sessions/missing.json"


def test_parse_reports_a_session_file_that_is_not_an_object(
    tmp_path: Path,
) -> None:
    path = _build_backup(
        tmp_path,
        manifest=_manifest([{"id": "session-1", "path": "sessions/1.json"}]),
        sessions={"sessions/1.json": ["not", "an", "object"]},
    )

    result = _only(path)

    assert result.error == "会话顶层结构不是有效的 JSON 对象"
    assert result.source_id == "session-1"


@pytest.mark.parametrize("bad_name", [None, 123])
def test_parse_reports_a_session_without_a_valid_name(
    tmp_path: Path,
    bad_name: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", name=bad_name),
    )

    result = _only(path)

    assert result.error == "会话中缺少有效的 name"


def test_parse_reports_a_session_without_a_messages_list(
    tmp_path: Path,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages="not-a-list"),
    )

    result = _only(path)

    assert result.error == "会话中缺少有效的 messages 列表"


def test_parse_reports_a_session_id_mismatch(tmp_path: Path) -> None:
    """索引里的 id 和会话文件里的 id 必须一致, 否则幂等键会指向错误的内容"""

    path = _single_session_backup(
        tmp_path,
        session=_session("different-id"),
    )

    result = _only(path)

    assert result.error == "会话索引项中的会话 id 与会话的 id 不一致"
    assert result.source_id == "session-1"


def test_parse_reports_a_backup_that_cannot_be_opened(tmp_path: Path) -> None:
    path = tmp_path / "not-a-zip.zip"
    path.write_text("plain text", encoding="utf-8")

    result = _only(path)

    assert result.error is not None
    assert result.error.startswith("无法读取或解析 Chatbox v2 备份: ")
    assert result.source_ref == str(path)


def test_parse_continues_after_a_broken_session_entry(tmp_path: Path) -> None:
    """一条会话坏掉不能影响同一份备份里的其他会话"""

    good_path = "sessions/good.json"
    path = _build_backup(
        tmp_path,
        manifest=_manifest(
            [
                {"id": "broken", "path": "sessions/missing.json"},
                {"id": "good", "path": good_path},
            ]
        ),
        sessions={good_path: _session("good")},
    )

    results = _parse(path)

    assert len(results) == 2
    assert results[0].error is not None
    assert results[1].conversation is not None
    assert results[1].conversation.source_id == "chatbox:good"


# ---------------------------------------------------------------------------
# parse: 成功路径与命名空间
# ---------------------------------------------------------------------------


def test_parse_builds_a_conversation_with_a_main_branch(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            name="我的会话",
            messages=[
                _message("m1", role="user", timestamp=1700000000000),
                _message("m2", role="assistant", timestamp=1700000060000),
            ],
        ),
    )

    result = _only(path)

    assert result.error is None
    assert result.source_id == "chatbox:session-1"
    assert result.source_ref == "sessions/session-1.json"
    assert result.warnings == []

    conversation = result.conversation
    assert conversation is not None
    assert conversation.source_id == "chatbox:session-1"
    assert conversation.title == "我的会话"
    assert conversation.source_entry == "sessions/session-1.json"
    assert conversation.source_type == SourceType.CHATBOX
    assert len(conversation.branches) == 1

    branch = conversation.branches[0]
    assert branch.source_id == "chatbox:session-1::main"
    assert branch.index == 0
    assert branch.fork_message_source_id is None
    assert branch.is_current is True
    assert [message.source_id for message in branch.messages] == [
        "chatbox:m1",
        "chatbox:m2",
    ]
    assert [message.role for message in branch.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert [message.position for message in branch.messages] == [0, 1]


def test_parse_derives_conversation_timestamps_from_messages(
    tmp_path: Path,
) -> None:
    """对话的时间范围是所有分支时间范围的并集"""

    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[
                _message("m1", timestamp=1700000060000),
                _message("m2", timestamp=1700000000000),
            ],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.created_at == datetime.fromtimestamp(
        1700000000, tz=timezone.utc
    )
    assert conversation.updated_at == datetime.fromtimestamp(
        1700000060, tz=timezone.utc
    )
    assert conversation.branches[0].created_at == conversation.created_at
    assert conversation.branches[0].updated_at == conversation.updated_at


def test_parse_leaves_timestamps_empty_when_no_message_has_one(
    tmp_path: Path,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", timestamp=None)],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.created_at is None
    assert conversation.updated_at is None
    assert conversation.branches[0].created_at is None
    assert conversation.branches[0].updated_at is None


def test_parse_emits_one_result_per_session_and_thread(tmp_path: Path) -> None:
    """thread 是独立的对话, 与所属会话平级产出"""

    session_path = "sessions/session-1.json"
    path = _build_backup(
        tmp_path,
        manifest=_manifest([{"id": "session-1", "path": session_path}]),
        sessions={
            session_path: _session(
                "session-1",
                threads=[
                    {
                        "id": "thread-1",
                        "name": "子话题",
                        "messages": [_message("t1")],
                    }
                ],
            )
        },
    )

    results = _parse(path)

    assert [result.source_id for result in results] == [
        "chatbox:session-1",
        "chatbox:session-1::thread::thread-1",
    ]
    thread_conversation = results[1].conversation
    assert thread_conversation is not None
    assert thread_conversation.title == "子话题"
    assert thread_conversation.branches[0].source_id == (
        "chatbox:session-1::thread::thread-1::main"
    )


# ---------------------------------------------------------------------------
# parse: thread 的容错
# ---------------------------------------------------------------------------


def test_parse_warns_when_threads_is_not_a_list(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", threads="not-a-list"),
    )

    result = _only(path)

    assert result.warnings == ["会话中的 threads 不是有效列表, 已忽略"]
    assert result.conversation is not None


def test_parse_warns_when_a_thread_is_not_an_object(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", threads=["not-an-object"]),
    )

    result = _only(path)

    assert result.warnings == ["第 0 个 thread 不是有效对象, 已跳过"]


@pytest.mark.parametrize("bad_id", [None, "", 123])
def test_parse_warns_when_a_thread_has_no_valid_id(
    tmp_path: Path,
    bad_id: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            threads=[{"id": bad_id, "name": "x", "messages": []}],
        ),
    )

    result = _only(path)

    assert result.warnings == ["第 0 个 thread 缺少有效的 id, 已跳过"]


def test_parse_warns_when_a_thread_has_no_valid_name(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            threads=[{"id": "thread-1", "name": 123, "messages": []}],
        ),
    )

    result = _only(path)

    assert result.warnings == ["thread thread-1 缺少有效的 name, 已跳过"]


def test_parse_warns_when_a_thread_has_no_messages_list(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            threads=[{"id": "thread-1", "name": "x", "messages": "nope"}],
        ),
    )

    result = _only(path)

    assert result.warnings == [
        "thread thread-1 缺少有效的 messages 列表, 已跳过"
    ]


# ---------------------------------------------------------------------------
# parse: 消息层的容错
# ---------------------------------------------------------------------------


def test_parse_warns_when_a_message_is_not_an_object(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=["not-an-object"]),
    )

    result = _only(path)

    assert result.warnings == [
        "分支 chatbox:session-1::main 的消息不是有效对象, 已跳过"
    ]


@pytest.mark.parametrize("bad_id", [None, "", 123])
def test_parse_warns_when_a_message_has_no_valid_id(
    tmp_path: Path,
    bad_id: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message(bad_id)]),
    )

    result = _only(path)

    assert result.warnings == [
        "分支 chatbox:session-1::main 的消息缺少有效的 id, 已跳过"
    ]


@pytest.mark.parametrize("bad_role", [None, "", 123])
def test_parse_warns_when_a_message_has_no_valid_role(
    tmp_path: Path,
    bad_role: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message("m1", role=bad_role)]),
    )

    result = _only(path)

    assert result.warnings == [
        "分支 chatbox:session-1::main 的消息 m1 缺少有效的 role, 已跳过"
    ]


def test_parse_warns_when_content_parts_is_not_a_list(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", parts="not-a-list")],
        ),
    )

    result = _only(path)

    assert result.warnings == [
        "分支 chatbox:session-1::main 的消息 m1 缺少有效的 contentParts, 已跳过"
    ]


def test_parse_warns_when_a_role_is_not_supported(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message("m1", role="tool")]),
    )

    result = _only(path)

    assert result.warnings == ["消息 m1 的角色 'tool' 不受支持, 已跳过"]
    conversation = result.conversation
    assert conversation is not None
    assert conversation.branches[0].messages == []


def test_skipped_messages_leave_no_position_gaps(tmp_path: Path) -> None:
    """position 是链内的实际序号, 被跳过的消息不能留下空洞"""

    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[
                _message("m1"),
                _message("m2", role="tool"),
                _message("m3"),
            ],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert [message.source_id for message in conversation.branches[0].messages] == [
        "chatbox:m1",
        "chatbox:m3",
    ]
    assert [message.position for message in conversation.branches[0].messages] == [0, 1]


# ---------------------------------------------------------------------------
# parse: 内容片段
# ---------------------------------------------------------------------------


def test_parse_joins_text_parts_without_a_separator(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[
                _message(
                    "m1",
                    parts=[
                        {"type": "text", "text": "第一段"},
                        {"type": "text", "text": "第二段"},
                    ],
                )
            ],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].content == "第一段第二段"


def test_parse_joins_reasoning_parts_with_a_newline(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[
                _message(
                    "m1",
                    parts=[
                        {"type": "reasoning", "text": "  第一步  "},
                        {"type": "reasoning", "text": "第二步"},
                    ],
                )
            ],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].thinking == "第一步\n第二步"


@pytest.mark.parametrize("marker", ["", "   ", "[redacted]", "[REDACTED]"])
def test_parse_drops_empty_thinking_markers(
    tmp_path: Path,
    marker: str,
) -> None:
    """思考链的占位内容不是内容, 清洗后为空就不该留下"""

    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[
                _message("m1", parts=[{"type": "reasoning", "text": marker}])
            ],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].thinking == ""


def test_parse_warns_when_a_part_is_not_an_object(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", parts=["not-an-object"])],
        ),
    )

    result = _only(path)

    assert result.warnings == [
        "消息 m1 的第 0 个内容片段不是有效对象, 已跳过"
    ]


def test_parse_warns_when_a_text_part_has_no_text(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", parts=[{"type": "text", "text": 123}])],
        ),
    )

    result = _only(path)

    assert result.warnings == ["消息 m1 的第 0 个 text 片段缺少有效文本"]


def test_parse_warns_when_a_reasoning_part_has_no_text(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", parts=[{"type": "reasoning", "text": 123}])],
        ),
    )

    result = _only(path)

    assert result.warnings == [
        "消息 m1 的第 0 个 reasoning 片段缺少有效文本"
    ]


def test_parse_always_warns_about_info_parts(tmp_path: Path) -> None:
    """工具链片段当前不落库, 但必须留下痕迹, 否则内容会静默丢失"""

    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", parts=[{"type": "info", "text": "工具调用"}])],
        ),
    )

    result = _only(path)

    assert result.warnings == ["消息 m1 的 info 片段被自动忽略"]


def test_parse_warns_about_an_unsupported_part_type(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", parts=[{"type": "video"}])],
        ),
    )

    result = _only(path)

    assert result.warnings == [
        "消息 m1 的第 0 个内容类型 'video' 暂不支持, 已跳过"
    ]


# ---------------------------------------------------------------------------
# parse: 模型名与时间戳
# ---------------------------------------------------------------------------


def test_parse_prefixes_the_model_with_the_provider(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", model="gpt-4", aiProvider="openai")],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].model == "openai/gpt-4"


def test_parse_falls_back_to_model_id(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message("m1", modelId="claude")]),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].model == "claude"


def test_parse_ignores_a_non_string_model(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message("m1", model=123)]),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].model is None


def test_parse_ignores_an_empty_provider(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", model="gpt-4", aiProvider="")],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].model == "gpt-4"


def test_parse_converts_a_millisecond_timestamp(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message("m1", timestamp=1700000000000)]),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].timestamp == datetime.fromtimestamp(
        1700000000, tz=timezone.utc
    )


def test_parse_accepts_a_float_timestamp(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", timestamp=1700000000500.0)],
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].timestamp == datetime.fromtimestamp(
        1700000000.5, tz=timezone.utc
    )


@pytest.mark.parametrize("bad_timestamp", [None, "1700000000000", True])
def test_parse_warns_when_the_timestamp_is_missing(
    tmp_path: Path,
    bad_timestamp: Any,
) -> None:
    """布尔值也是 int 的子类, 必须显式排除, 否则 True 会被当成 1 毫秒"""

    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message("m1", timestamp=bad_timestamp)]),
    )

    result = _only(path)

    assert result.warnings == ["消息 m1 缺少有效的 timestamp"]
    conversation = result.conversation
    assert conversation is not None
    assert conversation.branches[0].messages[0].timestamp is None


def test_parse_warns_when_the_timestamp_is_out_of_range(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", timestamp=10**20)],
        ),
    )

    result = _only(path)

    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("消息 m1 的 timestamp 存在问题: ")


# ---------------------------------------------------------------------------
# parse: 图片附件
# ---------------------------------------------------------------------------


def _image_resource(
    storage_key: str,
    path: str,
    *,
    mime_type: Any = "image/webp",
    size: Any = 1024,
    checksum: Any = None,
) -> dict[str, Any]:
    """构造一条 manifest.resources 记录"""

    resource: dict[str, Any] = {
        "originalStorageKeys": [storage_key],
        "path": path,
        "mimeType": mime_type,
        "size": size,
    }
    if checksum is not None:
        resource["checksum"] = checksum
    return resource


def _image_message(
    message_id: str = "m1",
    *,
    storage_key: Any = "key-1",
) -> dict[str, Any]:
    return _message(
        message_id,
        parts=[{"type": "image", "storageKey": storage_key}],
    )


def test_parse_builds_an_image_attachment(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[
            _image_resource(
                "key-1",
                "resources/1.webp",
                checksum={"algorithm": "sha256", "value": "abc"},
            )
        ],
        extra_files={"resources/1.webp": b"binary"},
    )

    conversation = _only(path).conversation
    assert conversation is not None

    attachments = conversation.branches[0].messages[0].attachments
    assert len(attachments) == 1
    assert attachments[0].attach_type == AttachmentType.IMAGE
    assert attachments[0].source_ref == "resources/1.webp"
    assert attachments[0].mime_type == "image/webp"
    assert attachments[0].size == 1024
    assert attachments[0].checksum == {"algorithm": "sha256", "value": "abc"}
    assert attachments[0].message_source_id == "chatbox:m1"


def test_parse_ignores_a_resource_without_storage_keys(tmp_path: Path) -> None:
    """resources 里的无效条目静默跳过, 它们不影响任何消息"""

    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[
            "not-an-object",
            {"originalStorageKeys": "not-a-list"},
            {"originalStorageKeys": [None, "", 123]},
        ],
        extra_files={"resources/1.webp": b"binary"},
    )

    result = _only(path)

    assert result.warnings == ["消息 m1 的 image 未找到对应资源: key-1"]


def test_parse_ignores_resources_that_are_not_a_list(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources="not-a-list",
    )

    result = _only(path)

    assert result.warnings == ["消息 m1 的 image 未找到对应资源: key-1"]


@pytest.mark.parametrize("bad_key", [None, "", 123])
def test_parse_warns_when_an_image_has_no_storage_key(
    tmp_path: Path,
    bad_key: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message(storage_key=bad_key)]),
    )

    result = _only(path)

    assert result.warnings == [
        "消息 m1 的第 0 个 image 片段缺少有效的 storageKey"
    ]


def test_parse_warns_when_an_image_resource_has_no_path(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[{"originalStorageKeys": ["key-1"], "path": None}],
    )

    result = _only(path)

    assert result.warnings == ["消息 m1 的 image 资源缺少有效的 path"]


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/etc/passwd",
        "../outside.webp",
        "resources/../../outside.webp",
        "resources\\1.webp",
    ],
)
def test_parse_rejects_unsafe_image_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    """资源路径来自外部文件, 绝对路径和目录穿越必须挡住"""

    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[_image_resource("key-1", unsafe_path)],
        extra_files={unsafe_path.lstrip("/"): b"binary"},
    )

    result = _only(path)

    assert result.warnings == [
        f"消息 m1 的 image 资源路径不安全: {unsafe_path}"
    ]


def test_parse_warns_when_the_image_file_is_missing_from_the_archive(
    tmp_path: Path,
) -> None:
    """manifest 里登记了资源, 但压缩包里没有对应文件"""

    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[_image_resource("key-1", "resources/1.webp")],
    )

    result = _only(path)

    assert result.warnings == [
        "消息 m1 的 image 资源文件不存在: resources/1.webp"
    ]


@pytest.mark.parametrize("bad_mime", [None, "", 123])
def test_parse_leaves_mime_type_empty_when_invalid(
    tmp_path: Path,
    bad_mime: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[_image_resource("key-1", "resources/1.webp", mime_type=bad_mime)],
        extra_files={"resources/1.webp": b"binary"},
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].attachments[0].mime_type is None


@pytest.mark.parametrize("bad_size", [None, -1, "1024", True, 1.5])
def test_parse_leaves_size_empty_when_invalid(
    tmp_path: Path,
    bad_size: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[_image_resource("key-1", "resources/1.webp", size=bad_size)],
        extra_files={"resources/1.webp": b"binary"},
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].attachments[0].size is None


@pytest.mark.parametrize(
    "bad_checksum",
    [
        "not-an-object",
        {"algorithm": "sha256"},
        {"value": "abc"},
        {"algorithm": "", "value": "abc"},
        {"algorithm": "sha256", "value": ""},
        {"algorithm": 1, "value": 2},
    ],
)
def test_parse_leaves_checksum_empty_when_invalid(
    tmp_path: Path,
    bad_checksum: Any,
) -> None:
    """校验值必须两半都有效, 只有一半时视为没有"""

    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_image_message()]),
        resources=[
            _image_resource("key-1", "resources/1.webp", checksum=bad_checksum)
        ],
        extra_files={"resources/1.webp": b"binary"},
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.branches[0].messages[0].attachments[0].checksum is None


# ---------------------------------------------------------------------------
# parse: 分叉分支
# ---------------------------------------------------------------------------


def _fork(
    *,
    branch_id: str = "fork-1",
    messages: Any = None,
) -> dict[str, Any]:
    """构造 messageForksHash 里的一条分叉记录"""

    return {
        "lists": [
            {
                "id": branch_id,
                "messages": [_message("f1")] if messages is None else messages,
            }
        ]
    }


def test_parse_builds_a_fork_branch(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={"m1": _fork()},
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert [branch.source_id for branch in conversation.branches] == [
        "chatbox:session-1::main",
        "chatbox:fork-1",
    ]
    fork = conversation.branches[1]
    assert fork.index == 0
    assert fork.fork_message_source_id == "chatbox:m1"
    assert fork.is_current is False
    assert [message.source_id for message in fork.messages] == ["chatbox:f1"]


def test_parse_propagates_forks_anchored_on_fork_messages(
    tmp_path: Path,
) -> None:
    """分叉可以以另一个分叉里的消息为锚点, 因此需要多轮处理"""

    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={
                "f1": _fork(branch_id="fork-2"),
                "m1": _fork(branch_id="fork-1"),
            },
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert [branch.source_id for branch in conversation.branches] == [
        "chatbox:session-1::main",
        "chatbox:fork-1",
        "chatbox:fork-2",
    ]
    assert conversation.branches[2].fork_message_source_id == "chatbox:f1"


def test_parse_warns_about_a_fork_whose_anchor_is_unknown(
    tmp_path: Path,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={"unknown": _fork()},
        ),
    )

    result = _only(path)

    assert result.warnings == ["分叉消息 unknown 无法找到所属的消息, 已跳过"]
    conversation = result.conversation
    assert conversation is not None
    assert len(conversation.branches) == 1


def test_parse_warns_about_an_invalid_fork_id(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={"": _fork()},
        ),
    )

    result = _only(path)

    assert result.warnings == ["messageForksHash 中存在无效的分叉消息 id, 已跳过"]


def test_parse_warns_when_fork_data_is_not_an_object(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={"m1": "not-an-object"},
        ),
    )

    result = _only(path)

    assert result.warnings == ["分叉消息 m1 的数据不是有效对象, 已跳过"]


def test_parse_warns_when_fork_lists_is_not_a_list(tmp_path: Path) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={"m1": {"lists": "not-a-list"}},
        ),
    )

    result = _only(path)

    assert result.warnings == ["分叉消息 m1 缺少有效的 lists 列表, 已跳过"]


def test_parse_warns_when_a_fork_branch_is_not_an_object(
    tmp_path: Path,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={"m1": {"lists": ["not-an-object"]}},
        ),
    )

    result = _only(path)

    assert result.warnings == [
        "分叉消息 m1 的第 0 个分支不是有效对象, 已跳过"
    ]


@pytest.mark.parametrize("bad_id", [None, "", 123])
def test_parse_warns_when_a_fork_branch_has_no_valid_id(
    tmp_path: Path,
    bad_id: Any,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={"m1": {"lists": [{"id": bad_id, "messages": []}]}},
        ),
    )

    result = _only(path)

    assert result.warnings == [
        "分叉消息 m1 的第 0 个分支缺少有效的 id, 已跳过"
    ]


def test_parse_warns_when_a_fork_branch_has_no_messages_list(
    tmp_path: Path,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash={
                "m1": {"lists": [{"id": "fork-1", "messages": "nope"}]}
            },
        ),
    )

    result = _only(path)

    assert result.warnings == ["分支 fork-1 缺少有效的 messages 列表, 已跳过"]


def test_parse_warns_when_message_forks_hash_is_not_an_object(
    tmp_path: Path,
) -> None:
    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1")],
            message_forks_hash="not-an-object",
        ),
    )

    result = _only(path)

    assert result.warnings == ["会话中的 messageForksHash 不是有效对象, 已忽略"]


def test_parse_accepts_a_missing_message_forks_hash(tmp_path: Path) -> None:
    """没有分叉字段是正常情况, 不该产生任何警告"""

    path = _single_session_backup(
        tmp_path,
        session=_session("session-1", messages=[_message("m1")]),
    )

    result = _only(path)

    assert result.warnings == []


def test_parse_derives_conversation_timestamps_from_forks_too(
    tmp_path: Path,
) -> None:
    """对话的时间范围必须覆盖分叉分支, 否则列表排序会漏掉较新的内容"""

    path = _single_session_backup(
        tmp_path,
        session=_session(
            "session-1",
            messages=[_message("m1", timestamp=1700000000000)],
            message_forks_hash={
                "m1": _fork(
                    messages=[_message("f1", timestamp=1700000600000)]
                )
            },
        ),
    )

    conversation = _only(path).conversation
    assert conversation is not None

    assert conversation.created_at == datetime.fromtimestamp(
        1700000000, tz=timezone.utc
    )
    assert conversation.updated_at == datetime.fromtimestamp(
        1700000600, tz=timezone.utc
    )
