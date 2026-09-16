"""导入服务的行为检查

覆盖 `ImportService` 的三条对外调用和全部内部编排分支:
- `import_file` 的三道前置检查(文件不存在, 路径不是文件, 格式不匹配)
- `find_duplicate_import` 的"失败批次不算重复"规则
- `import_results` 的批次统计, 警告与错误累积, 以及异常处理边界
- 重复导入时对管理域字段的保护(发布状态, 当前链标记, 消息编辑记录)
- `_validate_conversation` 的校验顺序

这些行为此前没有任何测试覆盖, 而它们决定了"一次导入到底算不算成功"
以及"重复导入会不会抹掉管理员做过的事", 属于最容易悄悄回归的部分.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterator

import pytest

from bootstrap import ServiceContainer
from core.enums import AttachmentType, ImportStatus, MessageRole, SourceType
from core.exceptions import ImportFailedError, ValidationError
from core.messages import MessageKey, render
from core.models import Attachment, Branch, Conversation, Message
from modules.interfaces.importing_intf import ParseResult
from modules.repositories import (
    ConversationRepository,
    ImportBatchRepository,
    MessageRepository,
)

CONVERSATION_ID = "conv-1"
MAIN_BRANCH = "conv-1::main"
FIRST_MESSAGE = "conv-1::main::msg-1"


@pytest.fixture
def container(tmp_path: Path) -> Iterator[ServiceContainer]:
    service_container = ServiceContainer.create(
        database_path=tmp_path / "import_service.db",
        initialize=True,
    )
    yield service_container
    service_container.close()


# === 测试替身 ===


@dataclass
class _FakeParse:
    """把固定对话图包成一次解析调用, 避免依赖真实的压缩包解析"""

    conversation: Conversation

    def results(self) -> Iterator[ParseResult]:
        yield ParseResult(
            conversation=self.conversation,
            source_id=self.conversation.source_id,
        )


class _FakeImporter:
    """可控的输入适配器替身, 只实现导入流程真正会用到的那部分"""

    format_key = "fake.v1"
    source_type = SourceType.CHATBOX

    def __init__(self, *, detected: bool = True) -> None:
        self.detected = detected
        self.parse_calls: list[Path] = []

    def detect(self, path: Path) -> bool:
        return self.detected

    def parse(self, path: Path) -> Iterator[ParseResult]:
        self.parse_calls.append(path)
        return iter(())


class _RaisingImporter(_FakeImporter):
    """解析阶段直接抛异常的适配器, 用于验证异常不会被吞掉"""

    def parse(self, path: Path) -> Iterator[ParseResult]:
        raise RuntimeError("适配器内部错误")


# === 构造辅助 ===


def _write_backup(workspace: Path, name: str, content: str) -> Path:
    """写一个内容可控的假备份文件, 只用于提供文件摘要"""

    path = workspace / name
    path.write_text(content, encoding="utf-8")
    return path


def _hash_of(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _build_conversation(
    *,
    source_id: str = CONVERSATION_ID,
    title: str = "测试对话",
    branch_source_id: str = MAIN_BRANCH,
    branch_index: int = 0,
    is_current: bool = True,
    message_source_id: str = FIRST_MESSAGE,
    message_content: str = "原始内容",
    message_position: int = 0,
    role: MessageRole = MessageRole.USER,
    attachments: list[Attachment] | None = None,
) -> Conversation:
    """构造一个只含一条分支和一条消息的对话图"""

    message = Message(
        source_id=message_source_id,
        role=role,
        content=message_content,
        position=message_position,
    )
    message.attachments.extend(attachments or [])

    return Conversation(
        source_id=source_id,
        title=title,
        branches=[
            Branch(
                source_id=branch_source_id,
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
):
    """走一次完整的导入, 文件内容与对话图分开控制"""

    return container.import_service.import_results(
        path=_write_backup(workspace, file_name, file_content),
        results=_FakeParse(conversation).results(),
        format_key="fake.v1",
    )


def _import_results(
    container: ServiceContainer,
    workspace: Path,
    file_name: str,
    file_content: str,
    results: Iterator[ParseResult],
):
    """直接投喂解析结果, 用于构造错误和警告场景"""

    return container.import_service.import_results(
        path=_write_backup(workspace, file_name, file_content),
        results=results,
        format_key="fake.v1",
    )


def _conversations(container: ServiceContainer) -> ConversationRepository:
    return ConversationRepository(container.connection)


def _messages(container: ServiceContainer) -> MessageRepository:
    return MessageRepository(container.connection)


def _batches(container: ServiceContainer) -> ImportBatchRepository:
    return ImportBatchRepository(container.connection)


# === import_file 的前置检查 ===


def test_import_file_rejects_missing_path(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """文件不存在时必须在读文件之前就失败, 而不是抛底层 IO 异常"""

    missing = tmp_path / "not-there.zip"

    with pytest.raises(ImportFailedError) as excinfo:
        container.import_service.import_file(missing, _FakeImporter())

    assert excinfo.value.key == MessageKey.IMPORT_FILE_NOT_FOUND
    assert str(missing) in str(excinfo.value)


def test_import_file_rejects_directory(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """路径存在但不是文件时, 报错要指向「不是文件」而不是「不存在"""

    directory = tmp_path / "a-directory"
    directory.mkdir()

    with pytest.raises(ImportFailedError) as excinfo:
        container.import_service.import_file(directory, _FakeImporter())

    assert excinfo.value.key == MessageKey.IMPORT_PATH_NOT_FILE


def test_import_file_rejects_format_mismatch(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """适配器不认这个文件时, 报错要带上适配器身份, 便于定位是哪个适配器拒收"""

    path = _write_backup(tmp_path, "backup.zip", "not a real backup")
    importer = _FakeImporter(detected=False)

    with pytest.raises(ImportFailedError) as excinfo:
        container.import_service.import_file(path, importer)

    assert excinfo.value.key == MessageKey.IMPORT_FORMAT_MISMATCH
    assert importer.format_key in str(excinfo.value)
    assert importer.parse_calls == []


def test_import_file_delegates_to_import_results(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """格式匹配时应当继续走解析和入库流程, 并把适配器的来源类型带下去"""

    path = _write_backup(tmp_path, "backup.zip", "content")
    importer = _FakeImporter()

    batch = container.import_service.import_file(path, importer)

    assert importer.parse_calls == [path]
    assert batch.format_key == "fake.v1"
    assert batch.source_type == SourceType.CHATBOX
    assert batch.file_name == "backup.zip"
    assert batch.file_hash == _hash_of("content")


def test_import_file_falls_back_to_other_source_type(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """适配器声明的来源名称无法识别时归入 other, 而不是让整次导入失败"""

    path = _write_backup(tmp_path, "backup.zip", "content")

    class _UnknownSource(_FakeImporter):
        source_type = "some-future-format"

    batch = container.import_service.import_file(path, _UnknownSource())

    assert batch.source_type == SourceType.OTHER


def test_import_file_accepts_importer_without_source_type(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """适配器完全没有声明 source_type 时同样归入 other"""

    path = _write_backup(tmp_path, "backup.zip", "content")

    class _NoSource(_FakeImporter):
        source_type = None

    batch = container.import_service.import_file(path, _NoSource())

    assert batch.source_type == SourceType.OTHER


# === find_duplicate_import ===


def test_find_duplicate_import_returns_none_for_empty_hash(
    container: ServiceContainer,
) -> None:
    """空摘要直接返回 None, 不能把「没有摘要」当成「匹配到了某个批次"""

    assert container.import_service.find_duplicate_import("") is None


def test_find_duplicate_import_returns_none_for_unknown_hash(
    container: ServiceContainer,
) -> None:
    assert container.import_service.find_duplicate_import("deadbeef") is None


def test_find_duplicate_import_returns_successful_batch(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    batch = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(),
    )

    found = container.import_service.find_duplicate_import(batch.file_hash)

    assert found is not None
    assert found.id == batch.id


def test_find_duplicate_import_ignores_failed_batch(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """失败批次不算重复, 否则一次失败会让同一份文件永远无法重试"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter([ParseResult(error="解析失败", source_id="s1")]),
    )
    assert batch.status == ImportStatus.FAILED

    assert container.import_service.find_duplicate_import(batch.file_hash) is None


# === import_results 的批次统计 ===


def test_import_results_records_successful_batch(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    batch = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(),
    )

    assert batch.status == ImportStatus.SUCCESS
    assert batch.total_count == 1
    assert batch.success_count == 1
    assert batch.failed_count == 0
    assert batch.error_summary is None
    assert batch.finished_at is not None
    assert batch.started_at <= batch.finished_at


def test_import_results_persists_batch(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """批次记录必须真的落库, 否则调用方事后无从查证"""

    batch = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(),
    )

    stored = _batches(container).get_by_id(batch.id)

    assert stored is not None
    assert stored.status == ImportStatus.SUCCESS
    assert stored.success_count == 1


def test_import_results_short_circuits_duplicate(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """同一份文件内容重复导入时直接返回原批次, 不重复写入库"""

    first = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(message_content="第一次"),
    )
    second = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(message_content="第二次"),
    )

    assert second.id == first.id

    message = container.query_service.get_message(FIRST_MESSAGE)
    assert message is not None
    assert message.content == "第一次"


def test_import_results_retries_after_failed_batch(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """上一次失败之后, 同一份文件必须还能重新导入"""

    failed = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter([ParseResult(error="解析失败", source_id="s1")]),
    )
    retried = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(),
    )

    assert retried.id != failed.id
    assert retried.status == ImportStatus.SUCCESS


def test_import_results_marks_all_failed_batch_as_failed(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """一条都没成功时批次整体失败"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(error="第一条失败", source_id="s1"),
                ParseResult(error="第二条失败", source_id="s2"),
            ]
        ),
    )

    assert batch.status == ImportStatus.FAILED
    assert batch.total_count == 2
    assert batch.success_count == 0
    assert batch.failed_count == 2


def test_import_results_keeps_partial_failure_as_success(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """部分失败仍然是成功批次

    批次状态回答的是"这次导入有没有整体成立", 而不是"有没有瑕疵".
    单条失败只体现在 failed_count 和 error_summary 上.
    """

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    conversation=_build_conversation(),
                    source_id=CONVERSATION_ID,
                ),
                ParseResult(error="第二条失败", source_id="s2"),
            ]
        ),
    )

    assert batch.status == ImportStatus.SUCCESS
    assert batch.total_count == 2
    assert batch.success_count == 1
    assert batch.failed_count == 1
    assert batch.error_summary is not None
    assert "第二条失败" in batch.error_summary


def test_import_results_counts_empty_result_as_failure(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """既没有 conversation 也没有 error 的结果算失败, 不能静默跳过"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter([ParseResult(source_id="s1", source_ref="sessions/s1.json")]),
    )

    assert batch.total_count == 1
    assert batch.success_count == 0
    assert batch.failed_count == 1
    assert batch.status == ImportStatus.FAILED
    assert batch.error_summary is not None
    assert render(MessageKey.IMPORT_RESULT_EMPTY) in batch.error_summary


def test_import_results_counts_zero_results_as_success(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """一个结果都没有时批次是成功的空批次, 而不是失败"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(()),
    )

    assert batch.status == ImportStatus.SUCCESS
    assert batch.total_count == 0
    assert batch.failed_count == 0


# === 错误与警告的累积格式 ===


def test_error_summary_appends_source_id_and_source_ref(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """错误文本要带上原始备份中的位置, 否则调用方无法定位是哪一条出的问题"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    error="解析失败",
                    source_id="session-1",
                    source_ref="sessions/session-1.json",
                )
            ]
        ),
    )

    assert batch.error_summary == (
        "解析失败 [source_id=session-1] [source_ref=sessions/session-1.json]"
    )


def test_error_summary_omits_missing_location(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """位置信息缺失时不留下空的方括号"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter([ParseResult(error="解析失败")]),
    )

    assert batch.error_summary == "解析失败"


def test_error_summary_joins_multiple_errors_with_newline(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(error="第一条失败", source_id="s1"),
                ParseResult(error="第二条失败", source_id="s2"),
            ]
        ),
    )

    assert batch.error_summary == (
        "第一条失败 [source_id=s1]\n第二条失败 [source_id=s2]"
    )


def test_warning_is_prefixed_and_recorded(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """警告必须带前缀, 否则调用方分不清哪一行是错误哪一行是警告"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    conversation=_build_conversation(),
                    source_id=CONVERSATION_ID,
                    warnings=["第 1 个 thread 不是有效对象, 已跳过"],
                )
            ]
        ),
    )

    assert batch.error_summary == "警告: 第 1 个 thread 不是有效对象, 已跳过"
    assert batch.failed_count == 0
    assert batch.status == ImportStatus.SUCCESS


def test_warning_after_error_is_appended_with_prefix(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """警告出现在错误之后时, 前缀要跟着换行一起补上"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(error="解析失败", source_id="s1"),
                ParseResult(
                    conversation=_build_conversation(),
                    source_id=CONVERSATION_ID,
                    warnings=["有内容被跳过"],
                ),
            ]
        ),
    )

    assert batch.error_summary == (
        "解析失败 [source_id=s1]\n警告: 有内容被跳过"
    )


def test_empty_warning_is_ignored(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """空警告不能污染 error_summary, 否则会留下一个孤零零的「警告: """

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    conversation=_build_conversation(),
                    source_id=CONVERSATION_ID,
                    warnings=["", ""],
                )
            ]
        ),
    )

    assert batch.error_summary is None


def test_warnings_are_recorded_before_error_check(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """同一条结果既有警告又有错误时, 两者都要留下"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    error="解析失败",
                    source_id="s1",
                    warnings=["有内容被跳过"],
                )
            ]
        ),
    )

    assert batch.error_summary == (
        "警告: 有内容被跳过\n解析失败 [source_id=s1]"
    )


# === 保存失败与异常边界 ===


def test_validation_failure_is_recorded_not_raised(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """单条内容校验失败只记一条错误, 不能中断整批导入"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    conversation=_build_conversation(title="   "),
                    source_id=CONVERSATION_ID,
                ),
                ParseResult(
                    conversation=_build_conversation(
                        source_id="conv-2",
                        branch_source_id="conv-2::main",
                        message_source_id="conv-2::main::msg-1",
                    ),
                    source_id="conv-2",
                ),
            ]
        ),
    )

    assert batch.total_count == 2
    assert batch.success_count == 1
    assert batch.failed_count == 1
    assert batch.status == ImportStatus.SUCCESS
    assert batch.error_summary is not None
    assert render(
        MessageKey.IMPORT_CONVERSATION_SAVE_FAILED,
        reason="ValidationError",
    ) in batch.error_summary


def test_save_failure_does_not_leak_exception_text(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """error_summary 面向调用方, 只写异常类型名, 不写异常正文"""

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    conversation=_build_conversation(title="   "),
                    source_id=CONVERSATION_ID,
                )
            ]
        ),
    )

    assert batch.error_summary is not None
    assert "对话标题不能为空" not in batch.error_summary
    assert "ValidationError" in batch.error_summary


def test_unexpected_exception_is_reraised_and_batch_persisted(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """解析器自身抛异常时必须向上抛, 但批次记录仍要落库

    否则失败原因只存在于内存里, 调用方事后无从查证.
    """

    def _exploding() -> Iterator[ParseResult]:
        # 必须写成生成器: 普通函数会在 import_results 被调用之前就抛异常,
        # 那样批次记录根本还没创建, 测不到"异常路径也要落库"这件事
        raise RuntimeError("适配器内部错误")
        yield  # pragma: no cover

    with pytest.raises(RuntimeError, match="适配器内部错误"):
        _import_results(
            container,
            tmp_path,
            "backup.zip",
            "content",
            _exploding(),
        )

    stored = _batches(container).get_by_file_hash(_hash_of("content"))

    assert stored is not None
    assert stored.status == ImportStatus.FAILED
    assert stored.finished_at is not None
    assert stored.error_summary == render(
        MessageKey.IMPORT_CONVERSATION_SAVE_FAILED,
        reason="RuntimeError",
    )


def test_unexpected_exception_does_not_leak_exception_text(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    def _exploding() -> Iterator[ParseResult]:
        raise RuntimeError("内部路径 C:/secret/place")
        yield  # pragma: no cover

    with pytest.raises(RuntimeError):
        _import_results(
            container,
            tmp_path,
            "backup.zip",
            "content",
            _exploding(),
        )

    stored = _batches(container).get_by_file_hash(_hash_of("content"))

    assert stored is not None
    assert stored.error_summary is not None
    assert "secret" not in stored.error_summary


def test_import_file_propagates_importer_exception(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """适配器解析阶段抛异常时, import_file 不能把它吞掉"""

    path = _write_backup(tmp_path, "backup.zip", "content")

    with pytest.raises(RuntimeError, match="适配器内部错误"):
        container.import_service.import_file(path, _RaisingImporter())


# === 重复导入对管理域字段的保护 ===


def test_reimport_preserves_published_state(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """发布状态属于管理域, 重复导入不能因为模型默认值而取消发布"""

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(),
    )

    repository = _conversations(container)
    stored = repository.get_by_source_id(CONVERSATION_ID)
    assert stored is not None
    stored.is_published = True
    repository.update(stored)

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(message_content="第二次"),
    )

    after = repository.get_by_source_id(CONVERSATION_ID)
    assert after is not None
    assert after.is_published is True


def test_reimport_preserves_current_branch_mark(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """当前链标记属于管理域, 重复导入不能把它重置回导入模型的默认值"""

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(is_current=False),
    )

    from modules.repositories import BranchRepository

    repository = BranchRepository(container.connection)
    stored = repository.get_by_source_id(MAIN_BRANCH)
    assert stored is not None
    stored.is_current = True
    repository.update(stored)

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(is_current=False, message_content="第二次"),
    )

    after = repository.get_by_source_id(MAIN_BRANCH)
    assert after is not None
    assert after.is_current is True


def test_reimport_overwrites_unedited_message(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """没被编辑过的消息允许按新解析结果覆盖"""

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content-1",
        _build_conversation(message_content="第一次"),
    )
    _import(
        container,
        tmp_path,
        "backup.zip",
        "content-2",
        _build_conversation(message_content="第二次"),
    )

    message = container.query_service.get_message(FIRST_MESSAGE)
    assert message is not None
    assert message.content == "第二次"


def test_reimport_does_not_overwrite_edited_message(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """已编辑过的消息保留原有内容和编辑记录, 重复导入不能抹掉管理员的修改"""

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(message_content="原始内容"),
    )

    repository = _messages(container)
    stored = repository.get_by_source_id(FIRST_MESSAGE)
    assert stored is not None
    stored.content = "管理员改过的内容"
    stored.edited_at = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
    repository.update(stored)

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(message_content="导入模型的新内容"),
    )

    after = repository.get_by_source_id(FIRST_MESSAGE)
    assert after is not None
    assert after.content == "管理员改过的内容"
    assert after.edited_at == datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)


def test_reimport_preserves_edited_by(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """编辑者身份同样属于管理域, 不能被导入模型覆盖成 None"""

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(),
    )

    container.user_service.register_admin("root", "pw-root")
    admin = container.user_service.get_by_username("root")
    assert admin is not None

    repository = _messages(container)
    stored = repository.get_by_source_id(FIRST_MESSAGE)
    assert stored is not None
    stored.edited_at = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
    stored.edited_by = admin.id
    repository.update(stored)

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(message_content="新内容"),
    )

    after = repository.get_by_source_id(FIRST_MESSAGE)
    assert after is not None
    assert after.edited_by == admin.id


def test_reimport_updates_attachment_in_place(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """附件主键是 (message_source_id, source_ref), 重复导入应当更新而不是新增"""

    attachment = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/1.webp",
        size=100,
    )

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content-1",
        _build_conversation(attachments=[attachment]),
    )

    updated = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/1.webp",
        size=200,
    )

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content-2",
        _build_conversation(attachments=[updated]),
    )

    stored = container.query_service.list_attachments(FIRST_MESSAGE)

    assert len(stored) == 1
    assert stored[0].size == 200


def test_reimport_adds_new_attachment(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """新增的附件引用要能补进去, 而不是被当成已存在而跳过"""

    first = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/1.webp",
    )
    second = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/2.webp",
    )

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content-1",
        _build_conversation(attachments=[first]),
    )
    _import(
        container,
        tmp_path,
        "backup.zip",
        "content-2",
        _build_conversation(attachments=[first, second]),
    )

    stored = container.query_service.list_attachments(FIRST_MESSAGE)

    assert sorted(item.source_ref for item in stored) == [
        "resources/1.webp",
        "resources/2.webp",
    ]


def test_attachment_lookup_happens_once_per_message(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """同一条消息的多个附件只查一次附件表

    附件主键是 (message_source_id, source_ref), 判断"是否已存在"只需要按
    source_ref 查一次. 实现把这次查询提到逐附件的循环之外, 因此 N 个附件
    只产生 1 次查询. 本测试把这个行为固定下来, 防止将来有人把查询挪回
    循环内部.
    """

    attachments = [
        Attachment(
            message_source_id=FIRST_MESSAGE,
            attach_type=AttachmentType.IMAGE,
            source_ref=f"resources/{index}.webp",
        )
        for index in range(3)
    ]

    repository = container.import_service.attachment_repository
    original = repository.list_by_message
    calls: list[str] = []

    def _counting(message_source_id: str):
        calls.append(message_source_id)
        return original(message_source_id)

    repository.list_by_message = _counting  # type: ignore[method-assign]

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(attachments=attachments),
    )

    assert calls == [FIRST_MESSAGE]


# === _validate_conversation 的校验顺序 ===


def _validation_error_for(
    container: ServiceContainer,
    tmp_path: Path,
    conversation: Conversation,
) -> str:
    """导入一个非法对话, 返回校验器给出的错误文本

    这里刻意直接调用 `_validate_conversation`, 而不是读批次的 error_summary:
    `_handle_parse_result` 会把 ValidationError 吞掉, 只往 error_summary 里写
    「保存会话失败: ValidationError」, 具体是哪条校验规则并没有落进去.
    要观察校验顺序和具体规则, 只能直接拿校验器抛出的异常.
    """

    with pytest.raises(ValidationError) as excinfo:
        container.import_service._validate_conversation(conversation)

    return str(excinfo.value)


@pytest.mark.parametrize(
    ("conversation", "key"),
    [
        (
            _build_conversation(source_id="   "),
            MessageKey.CONVERSATION_SOURCE_ID_EMPTY,
        ),
        (
            _build_conversation(title="   "),
            MessageKey.CONVERSATION_TITLE_EMPTY,
        ),
        (
            _build_conversation(branch_source_id="   "),
            MessageKey.BRANCH_SOURCE_ID_EMPTY,
        ),
        (
            _build_conversation(branch_index=-1),
            MessageKey.BRANCH_INDEX_NEGATIVE,
        ),
        (
            _build_conversation(message_source_id="   "),
            MessageKey.MESSAGE_SOURCE_ID_EMPTY,
        ),
        (
            _build_conversation(message_position=-1),
            MessageKey.MESSAGE_POSITION_NEGATIVE,
        ),
    ],
)
def test_validation_rejects_invalid_conversation(
    container: ServiceContainer,
    tmp_path: Path,
    conversation: Conversation,
    key: MessageKey,
) -> None:
    """校验失败时错误文本里必须带上具体原因, 而不是只写「保存失败"""

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(key) in summary


def test_validation_rejects_duplicated_branch_source_id(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """同一对话内两条分支用同一个 source_id 时必须报错, 否则会静默丢一条"""

    conversation = _build_conversation()
    conversation.branches.append(
        Branch(
            source_id=MAIN_BRANCH,
            index=1,
            messages=[
                Message(
                    source_id="conv-1::main::msg-2",
                    role=MessageRole.USER,
                    content="第二条",
                    position=0,
                )
            ],
        )
    )

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(
        MessageKey.BRANCH_SOURCE_ID_DUPLICATED,
        branch_source_id=MAIN_BRANCH,
    ) in summary


def test_validation_rejects_duplicated_message_source_id(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    conversation = _build_conversation()
    conversation.branches[0].messages.append(
        Message(
            source_id=FIRST_MESSAGE,
            role=MessageRole.USER,
            content="重复标识",
            position=1,
        )
    )

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(
        MessageKey.MESSAGE_SOURCE_ID_DUPLICATED,
        message_source_id=FIRST_MESSAGE,
    ) in summary


def test_validation_rejects_duplicated_message_position(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """同一分支内两条消息占同一个 position 时必须报错, 否则展示顺序不确定"""

    conversation = _build_conversation()
    conversation.branches[0].messages.append(
        Message(
            source_id="conv-1::main::msg-2",
            role=MessageRole.USER,
            content="重复序号",
            position=0,
        )
    )

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(
        MessageKey.MESSAGE_POSITION_DUPLICATED,
        position=0,
    ) in summary


def test_validation_rejects_unsupported_role(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """角色不在枚举内时必须报错, 而不是让 CHECK 约束在写库时才炸"""

    conversation = _build_conversation()
    conversation.branches[0].messages[0].role = "tool"  # type: ignore[assignment]

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(MessageKey.MESSAGE_ROLE_UNSUPPORTED, role="tool") in summary


def test_validation_rejects_attachment_message_mismatch(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """附件挂到了别的消息上时必须报错, 否则会写出一条指向不存在消息的附件"""

    attachment = Attachment(
        message_source_id="conv-1::main::msg-999",
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/1.webp",
    )

    summary = _validation_error_for(
        container,
        tmp_path,
        _build_conversation(attachments=[attachment]),
    )

    assert render(
        MessageKey.ATTACHMENT_MESSAGE_MISMATCH,
        message_source_id="conv-1::main::msg-999",
    ) in summary


def test_validation_rejects_empty_attachment_source_ref(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    attachment = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="   ",
    )

    summary = _validation_error_for(
        container,
        tmp_path,
        _build_conversation(attachments=[attachment]),
    )

    assert render(MessageKey.ATTACHMENT_SOURCE_REF_EMPTY) in summary


def test_validation_rejects_unsupported_attachment_type(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    attachment = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type="video",  # type: ignore[arg-type]
        source_ref="resources/1.webp",
    )

    summary = _validation_error_for(
        container,
        tmp_path,
        _build_conversation(attachments=[attachment]),
    )

    assert render(
        MessageKey.ATTACHMENT_TYPE_UNSUPPORTED,
        attach_type="video",
    ) in summary


def test_validation_rejects_negative_attachment_size(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    attachment = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/1.webp",
        size=-1,
    )

    summary = _validation_error_for(
        container,
        tmp_path,
        _build_conversation(attachments=[attachment]),
    )

    assert render(MessageKey.ATTACHMENT_SIZE_NEGATIVE) in summary


def test_validation_accepts_none_attachment_size(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """size 为 None 表示未知, 不是错误"""

    attachment = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/1.webp",
        size=None,
    )

    batch = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(attachments=[attachment]),
    )

    assert batch.success_count == 1
    assert batch.failed_count == 0


def test_validation_rejects_empty_conversation_source_id_before_lookup(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """source_id 为空时必须在查库之前就失败, 不能拿空串去查已有对话"""

    summary = _validation_error_for(
        container,
        tmp_path,
        _build_conversation(source_id="   "),
    )

    assert render(MessageKey.CONVERSATION_SOURCE_ID_EMPTY) in summary
    assert render(MessageKey.CONVERSATION_SOURCE_ID_REQUIRED) not in summary


def test_validation_checks_conversation_before_branches(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """对话级问题优先于分支级问题, 报错要指向最外层的原因"""

    conversation = _build_conversation(title="   ", branch_index=-1)

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(MessageKey.CONVERSATION_TITLE_EMPTY) in summary
    assert render(MessageKey.BRANCH_INDEX_NEGATIVE) not in summary


def test_validation_checks_branch_before_messages(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    conversation = _build_conversation(branch_index=-1, message_position=-1)

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(MessageKey.BRANCH_INDEX_NEGATIVE) in summary
    assert render(MessageKey.MESSAGE_POSITION_NEGATIVE) not in summary


def test_validation_checks_message_before_attachments(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    attachment = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="   ",
    )
    conversation = _build_conversation(
        message_position=-1,
        attachments=[attachment],
    )

    summary = _validation_error_for(container, tmp_path, conversation)

    assert render(MessageKey.MESSAGE_POSITION_NEGATIVE) in summary
    assert render(MessageKey.ATTACHMENT_SOURCE_REF_EMPTY) not in summary


# === 落库内容 ===


def test_import_writes_conversation_graph(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """一次成功导入必须把对话, 分支, 消息和附件全部写进去"""

    attachment = Attachment(
        message_source_id=FIRST_MESSAGE,
        attach_type=AttachmentType.IMAGE,
        source_ref="resources/1.webp",
    )

    _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(attachments=[attachment]),
    )

    detail = container.query_service.get_conversation_detail(CONVERSATION_ID)

    assert detail is not None
    assert detail.conversation.title == "测试对话"
    assert [branch.source_id for branch in detail.branches] == [MAIN_BRANCH]
    assert [message.source_id for message in detail.messages[MAIN_BRANCH]] == [
        FIRST_MESSAGE
    ]
    assert [item.source_ref for item in detail.attachments[FIRST_MESSAGE]] == [
        "resources/1.webp"
    ]


def test_import_fills_batch_back_reference(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """对话要回指导入批次, 否则无法回答「这条内容是哪次导入带进来的"""

    batch = _import(
        container,
        tmp_path,
        "backup.zip",
        "content",
        _build_conversation(),
    )

    stored = _conversations(container).get_by_source_id(CONVERSATION_ID)

    assert stored is not None
    assert stored.import_batch_id == batch.id
    assert stored.source_archive == "backup.zip"


def test_import_rolls_back_conversation_on_write_failure(
    container: ServiceContainer,
    tmp_path: Path,
) -> None:
    """写入过程中出错时, 已经写进去的部分要随事务回滚, 不能留下半份数据"""

    conversation = _build_conversation()
    conversation.branches.append(
        Branch(
            source_id="conv-1::main",
            index=1,
            messages=[
                Message(
                    source_id="conv-1::main::msg-2",
                    role=MessageRole.USER,
                    content="第二条",
                    position=0,
                )
            ],
        )
    )

    batch = _import_results(
        container,
        tmp_path,
        "backup.zip",
        "content",
        iter(
            [
                ParseResult(
                    conversation=conversation,
                    source_id=CONVERSATION_ID,
                )
            ]
        ),
    )

    assert batch.failed_count == 1
    assert _conversations(container).get_by_source_id(CONVERSATION_ID) is None
