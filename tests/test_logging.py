"""日志配置与格式化器的行为检查

覆盖 ``utils/logging.py`` 的三块能力:
- ``configure_logging`` 的幂等性, 级别名解析与非法级别名的报错
- ``TextFormatter`` 的行式输出形状
- ``JsonFormatter`` 的单行 JSON 输出形状

以及两条容易被忽略的约定:
- ``extra`` 里字段名命中敏感片段时取值被替换为 ``***``
- 脱敏只看字段名, 不看消息正文 —— 正文里的口令不会被替换

最后一条是刻意设计而不是缺陷, 用例把它固定下来, 免得将来有人误以为
"日志已经自动脱敏" 而把口令拼进消息正文.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from utils.logging import (
    JsonFormatter,
    TextFormatter,
    _ChatVaultHandler,
    _extra_fields,
    _is_sensitive,
    _timestamp,
    configure_logging,
)

# 探针实测得到的固定时间戳: 2026-09-16T12:36:01.916+00:00
_FIXED_CREATED = 1789562161.916
_FIXED_TIMESTAMP = "2026-09-16T12:36:01.916+00:00"


def _record(
    *,
    message: str = "导入完成 x",
    args: tuple[Any, ...] = (),
    level: int = logging.INFO,
    name: str = "chat_vault.test",
    created: float = _FIXED_CREATED,
    exc_info: Any = None,
    stack_info: str | None = None,
    extra: dict[str, Any] | None = None,
) -> logging.LogRecord:
    """构造一条日志记录

    直接调 ``makeRecord`` 而不是走 ``logger.info``, 这样不需要安装处理器,
    也不会污染根日志器. ``extra`` 是第 9 个位置参数, 这里一律用关键字传,
    避免将来 logging 调整参数顺序时静默错位.
    """

    logger = logging.getLogger(name)
    record = logger.makeRecord(
        name,
        level,
        "test_logging.py",
        1,
        message,
        args,
        exc_info,
        func="test",
        extra=extra,
        sinfo=stack_info,
    )
    record.created = created
    return record


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Any:
    """保存并还原根日志器的处理器与级别

    ``configure_logging`` 会改动全局状态, 用例跑完必须还原, 否则会影响
    同一进程里其它测试文件的日志行为.
    """

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level

    yield

    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in saved_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(saved_level)


def _chat_vault_handlers() -> list[logging.Handler]:
    """取根日志器上由本模块安装的处理器"""

    return [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, _ChatVaultHandler)
    ]


class TestConfigureLogging:
    """``configure_logging`` 的配置行为"""

    def test_installs_exactly_one_handler(self) -> None:
        """首次调用安装一个处理器"""

        configure_logging()

        assert len(_chat_vault_handlers()) == 1

    def test_repeated_calls_do_not_stack_handlers(self) -> None:
        """重复调用不会叠加输出

        这是幂等性的核心: 每次调用先移除自己此前安装的处理器, 因此调用
        三次之后仍然只有一个.
        """

        configure_logging()
        configure_logging()
        configure_logging()

        assert len(_chat_vault_handlers()) == 1

    def test_repeated_calls_keep_foreign_handlers(self) -> None:
        """重复调用保留宿主进程自己添加的处理器

        本模块被嵌入到别的进程 (例如测试收集器) 时, 不能顺手删掉宿主的
        处理器.
        """

        foreign = logging.StreamHandler()
        logging.getLogger().addHandler(foreign)

        configure_logging()
        configure_logging()

        assert foreign in logging.getLogger().handlers
        assert len(_chat_vault_handlers()) == 1

    def test_accepts_integer_level(self) -> None:
        """整数级别直接生效"""

        configure_logging(logging.DEBUG)

        assert logging.getLogger().level == logging.DEBUG

    def test_accepts_level_name(self) -> None:
        """级别名按名字解析"""

        configure_logging("WARNING")

        assert logging.getLogger().level == logging.WARNING

    def test_level_name_is_case_insensitive(self) -> None:
        """级别名大小写不敏感"""

        configure_logging("debug")

        assert logging.getLogger().level == logging.DEBUG

    def test_unknown_level_name_raises(self) -> None:
        """无法识别的级别名立刻失败

        启动配置错误应当立刻暴露, 而不是悄悄退回默认级别.
        """

        with pytest.raises(ValueError) as excinfo:
            configure_logging("VERBOSE")

        assert "VERBOSE" in str(excinfo.value)

    def test_unknown_level_name_leaves_root_untouched(self) -> None:
        """级别名非法时根日志器不被改动

        校验发生在改动之前, 因此失败调用不会留下半个配置.
        """

        logging.getLogger().setLevel(logging.ERROR)
        before = len(_chat_vault_handlers())

        with pytest.raises(ValueError):
            configure_logging("VERBOSE")

        assert logging.getLogger().level == logging.ERROR
        assert len(_chat_vault_handlers()) == before

    def test_default_formatter_is_text(self) -> None:
        """默认安装行式文本格式化器"""

        configure_logging()

        assert isinstance(_chat_vault_handlers()[0].formatter, TextFormatter)

    def test_json_output_switches_formatter(self) -> None:
        """``json_output=True`` 换成 JSON 格式化器"""

        configure_logging(json_output=True)

        assert isinstance(_chat_vault_handlers()[0].formatter, JsonFormatter)

    def test_switching_back_to_text_replaces_formatter(self) -> None:
        """先 JSON 后文本时格式化器被替换而不是叠加"""

        configure_logging(json_output=True)
        configure_logging(json_output=False)

        handlers = _chat_vault_handlers()
        assert len(handlers) == 1
        assert isinstance(handlers[0].formatter, TextFormatter)

    def test_handler_writes_to_stderr(self) -> None:
        """处理器写标准错误而不是标准输出

        标准输出留给程序自身的产物, 日志混进去会破坏管道用法.
        """

        import sys

        configure_logging()

        assert _chat_vault_handlers()[0].stream is sys.stderr


class TestTimestamp:
    """时间戳格式"""

    def test_uses_utc_with_millisecond_precision(self) -> None:
        """统一 UTC 且精确到毫秒"""

        assert _timestamp(_record()) == _FIXED_TIMESTAMP

    def test_matches_expected_offset(self) -> None:
        """时间戳带 UTC 偏移量而不是本地时区"""

        moment = datetime.fromtimestamp(_FIXED_CREATED, tz=timezone.utc)

        assert moment.isoformat(timespec="milliseconds") == _FIXED_TIMESTAMP


class TestSensitiveDetection:
    """敏感字段名判定"""

    @pytest.mark.parametrize(
        "field_name",
        [
            "password",
            "passwd",
            "secret",
            "token",
            "api_key",
            "apikey",
            "authorization",
            "credential",
        ],
    )
    def test_known_fragments_are_sensitive(self, field_name: str) -> None:
        """八个约定片段都能命中"""

        assert _is_sensitive(field_name) is True

    @pytest.mark.parametrize(
        "field_name",
        [
            "PASSWORD",
            "UserPassword",
            "access_token",
            "API_KEY",
            "Authorization",
        ],
    )
    def test_matching_is_case_insensitive_and_substring(
        self,
        field_name: str,
    ) -> None:
        """判定按小写后的子串匹配, 因此大小写和前后缀都不影响"""

        assert _is_sensitive(field_name) is True

    @pytest.mark.parametrize(
        "field_name",
        ["username", "batch_id", "count", "path", "source_ref"],
    )
    def test_ordinary_names_are_not_sensitive(self, field_name: str) -> None:
        """普通业务字段名不命中"""

        assert _is_sensitive(field_name) is False


class TestExtraFields:
    """``extra`` 结构化字段的提取"""

    def test_extracts_custom_fields(self) -> None:
        """调用方附加的字段被取出"""

        record = _record(extra={"batch_id": "b1", "count": 3})

        assert _extra_fields(record) == {"batch_id": "b1", "count": 3}

    def test_no_extra_yields_empty_mapping(self) -> None:
        """没有附加字段时返回空映射"""

        assert _extra_fields(_record()) == {}

    def test_standard_attributes_are_filtered_out(self) -> None:
        """logging 自身的属性不算业务字段

        否则每条日志都会带上 name, levelname, lineno 等一堆噪音.
        """

        fields = _extra_fields(_record())

        for standard in ("name", "levelname", "lineno", "msg", "args"):
            assert standard not in fields

    def test_task_name_is_treated_as_standard(self) -> None:
        """``taskName`` 属于 logging 自身属性

        Python 3.12 起 ``LogRecord`` 自带 ``taskName``, 因此它必须留在标准
        属性集合里, 否则每条日志都会多出一个 ``taskName=None`` 的噪音字段.
        调用方也无法通过 ``extra`` 传同名键 —— logging 自己会抛 ``KeyError``.
        """

        record = _record()

        assert "taskName" in record.__dict__
        assert "taskName" not in _extra_fields(record)

    def test_extra_cannot_shadow_a_standard_attribute(self) -> None:
        """``extra`` 传标准属性名时由 logging 自己拒绝

        这条不是本模块的行为, 而是记录一个容易踩的坑: 想给日志加字段时
        不能挑 ``taskName``, ``name``, ``message`` 这类名字.
        """

        with pytest.raises(KeyError):
            _record(extra={"taskName": "y"})

    def test_underscore_prefixed_keys_are_dropped(self) -> None:
        """下划线开头的键被丢弃

        这类键是内部约定, 不属于对外输出的结构化字段.
        """

        record = _record(extra={"_hidden": 1, "visible": 2})

        assert _extra_fields(record) == {"visible": 2}

    def test_sensitive_field_value_is_redacted(self) -> None:
        """敏感字段名对应的取值被替换为固定标记"""

        record = _record(extra={"password": "hunter2", "batch_id": "b1"})

        assert _extra_fields(record) == {"password": "***", "batch_id": "b1"}

    def test_redaction_keeps_the_field_name(self) -> None:
        """脱敏保留字段名

        保留名字才能看出"这里本来有个口令字段", 直接删掉反而让人以为
        调用方没传.
        """

        record = _record(extra={"api_key": "sk-123"})

        assert list(_extra_fields(record)) == ["api_key"]

    def test_redaction_does_not_inspect_message_body(self) -> None:
        """脱敏只看字段名, 不看消息正文

        这是已知边界: 口令被拼进消息正文时格式化器无从分辨. 用例把它固定
        下来, 提醒调用方不要把敏感值写进消息.
        """

        record = _record(message="登录失败: hunter2")

        assert _extra_fields(record) == {}
        assert "hunter2" in TextFormatter().format(record)


class TestTextFormatter:
    """行式文本输出"""

    def test_basic_line_shape(self) -> None:
        """时间戳, 级别, 日志器名, 消息依次排列"""

        line = TextFormatter().format(_record())

        assert line == f"{_FIXED_TIMESTAMP} INFO    chat_vault.test 导入完成 x"

    def test_level_name_is_padded(self) -> None:
        """级别名左对齐补齐到 7 列

        补齐之后消息正文的起始列在不同级别下保持一致, 便于人眼扫读.
        """

        line = TextFormatter().format(_record(level=logging.WARNING))

        assert "WARNING chat_vault.test" in line

    def test_extra_fields_are_appended(self) -> None:
        """结构化字段追加在消息之后"""

        record = _record(extra={"batch_id": "b1", "password": "pw"})

        line = TextFormatter().format(record)

        assert line == (
            f"{_FIXED_TIMESTAMP} INFO    chat_vault.test 导入完成 x "
            "batch_id='b1' password='***'"
        )

    def test_no_extra_means_no_trailing_space(self) -> None:
        """没有附加字段时不留下多余空格"""

        line = TextFormatter().format(_record())

        assert not line.endswith(" ")

    def test_message_arguments_are_interpolated(self) -> None:
        """``%s`` 占位符按 logging 的规则插值"""

        record = _record(message="导入完成 %s", args=("backup.zip",))

        assert "导入完成 backup.zip" in TextFormatter().format(record)

    def test_exception_is_rendered_on_following_lines(self) -> None:
        """异常堆栈另起一行追加"""

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            record = _record(exc_info=sys.exc_info())

        line = TextFormatter().format(record)

        assert line.startswith(f"{_FIXED_TIMESTAMP} INFO    chat_vault.test 导入完成 x")
        assert "\n" in line
        assert "RuntimeError: boom" in line

    def test_stack_info_is_rendered(self) -> None:
        """``stack_info`` 另起一行追加"""

        record = _record(stack_info="Stack (most recent call last):\n  fake frame")

        line = TextFormatter().format(record)

        assert "Stack (most recent call last):" in line
        assert "fake frame" in line

    def test_non_string_field_values_use_repr(self) -> None:
        """字段取值用 ``repr`` 渲染

        这样字符串带引号, 数字不带, 人眼能区分 ``'3'`` 和 ``3``.
        """

        record = _record(extra={"count": 3, "path": Path("a/b")})

        line = TextFormatter().format(record)

        assert "count=3" in line
        assert "path=PosixPath('a/b')" in line or "path=WindowsPath('a/b')" in line


class TestJsonFormatter:
    """单行 JSON 输出"""

    def test_output_is_single_line(self) -> None:
        """每条日志一行完整 JSON

        多行会破坏按行采集的日志管道.
        """

        record = _record(extra={"batch_id": "b1"})

        assert "\n" not in JsonFormatter().format(record)

    def test_basic_payload_shape(self) -> None:
        """四个固定键: time, level, logger, message"""

        payload = json.loads(JsonFormatter().format(_record()))

        assert payload == {
            "time": _FIXED_TIMESTAMP,
            "level": "INFO",
            "logger": "chat_vault.test",
            "message": "导入完成 x",
        }

    def test_fields_key_appears_only_when_needed(self) -> None:
        """没有附加字段时不出现 ``fields`` 键"""

        payload = json.loads(JsonFormatter().format(_record()))

        assert "fields" not in payload

    def test_fields_are_nested_and_typed(self) -> None:
        """结构化字段保持独立且保留原始类型

        这是 JSON 格式相对文本格式的价值: 检索时不需要做文本解析.
        """

        record = _record(extra={"batch_id": "b1", "count": 3})

        payload = json.loads(JsonFormatter().format(record))

        assert payload["fields"] == {"batch_id": "b1", "count": 3}

    def test_sensitive_field_is_redacted(self) -> None:
        """敏感字段在 JSON 里同样被脱敏"""

        record = _record(extra={"password": "pw", "batch_id": "b1"})

        payload = json.loads(JsonFormatter().format(record))

        assert payload["fields"] == {"password": "***", "batch_id": "b1"}

    def test_chinese_is_not_escaped(self) -> None:
        """中文按原样输出而不是 ``\\uXXXX`` 转义

        转义之后日志文件几乎无法人工阅读.
        """

        output = JsonFormatter().format(_record())

        assert "导入完成" in output
        assert "\\u5bfc" not in output

    def test_unserializable_value_falls_back_to_str(self) -> None:
        """无法序列化的取值退化为字符串而不是丢掉整条日志

        ``Path``, ``datetime`` 这类对象在结构化字段里很常见, 因为一个字段
        序列化失败就丢掉整条日志是不可接受的.
        """

        record = _record(extra={"path": Path("a/b")})

        payload = json.loads(JsonFormatter().format(record))

        assert "a" in payload["fields"]["path"]

    def test_exception_is_a_separate_key(self) -> None:
        """异常堆栈放在 ``exception`` 键里"""

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            record = _record(exc_info=sys.exc_info())

        payload = json.loads(JsonFormatter().format(record))

        assert "RuntimeError: boom" in payload["exception"]

    def test_stack_info_is_a_separate_key(self) -> None:
        """``stack_info`` 放在 ``stack`` 键里"""

        record = _record(stack_info="Stack (most recent call last):\n  fake frame")

        payload = json.loads(JsonFormatter().format(record))

        assert "fake frame" in payload["stack"]

    def test_exception_output_stays_single_line(self) -> None:
        """带异常时仍然只有一行

        堆栈里的换行被 JSON 转义成 ``\\n``, 不会真的换行.
        """

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            record = _record(exc_info=sys.exc_info())

        assert "\n" not in JsonFormatter().format(record)


class TestEndToEnd:
    """通过真实日志器走一遍完整链路"""

    def test_message_reaches_the_handler(self, capsys: Any) -> None:
        """``logger.info`` 的输出真的落到标准错误

        前面的用例都直接调格式化器, 这里补一条端到端的检查, 确认处理器
        确实挂在根日志器上并且级别放行.
        """

        configure_logging(logging.INFO)

        logging.getLogger("chat_vault.e2e").info(
            "导入完成",
            extra={"batch_id": "b1"},
        )

        captured = capsys.readouterr()

        assert "导入完成" in captured.err
        assert "batch_id='b1'" in captured.err

    def test_below_level_messages_are_suppressed(self, capsys: Any) -> None:
        """低于配置级别的日志不输出"""

        configure_logging(logging.WARNING)

        logging.getLogger("chat_vault.e2e").info("不该出现")

        assert "不该出现" not in capsys.readouterr().err

    def test_json_mode_end_to_end(self, capsys: Any) -> None:
        """JSON 模式下标准错误里是可直接解析的 JSON"""

        configure_logging(logging.INFO, json_output=True)

        logging.getLogger("chat_vault.e2e").info("导入完成", extra={"count": 3})

        line = capsys.readouterr().err.strip()
        payload = json.loads(line)

        assert payload["message"] == "导入完成"
        assert payload["fields"] == {"count": 3}
