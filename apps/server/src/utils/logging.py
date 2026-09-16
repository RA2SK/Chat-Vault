"""提供应用各层使用的面向开发者的日志配置, 记录和格式化能力

分工约定:
- 只由进程入口 (`main.py`, `cli.py`) 调用 `configure_logging`, 且只调用一次
- 库代码用 ``logging.getLogger(__name__)`` 取日志器, 
  不自行添加处理器,不设置级别, 不修改全局配置
- 异常只在出口层记录. 中间层不要既记录又抛出
- 需要附带变量时用 ``extra`` 传结构化字段:
      logger.info("导入完成", extra={"batch_id": batch.id, "count": count})
- 不记录密码, 密码散列, 令牌等敏感值

"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

__all__ = ["configure_logging"]

# logging.LogRecord 自身的属性, 不属于调用方通过 extra 传进来的结构化字段
_STANDARD_RECORD_ATTRIBUTES = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "stacklevel",
        "taskName",
        "thread",
        "threadName",
    }
)

# 字段名里出现以下片段时按敏感处理, 只保留字段名, 取值替换为固定标记
#
# 注意这条防线只覆盖 extra 字段的"名字", 不检查字段的"内容". 也就是说
# ``logger.info("登录失败", extra={"username": name})`` 会被脱敏, 而
# ``logger.info("登录失败: %s", password)`` 不会 —— 后者把口令写进了消息正文,
# 格式化器无从分辨.
#
# 因此消息正文里放什么由调用方负责: 不要把口令, 令牌, 凭据或用户提交的
# 原文拼进日志消息. 需要记录这类上下文时, 用 extra 传字段, 让字段名去触发
# 脱敏. 这里刻意不做基于内容的猜测式脱敏: 正则匹配正文既会漏掉变形写法,
# 又会把正常内容误伤成 ***, 反而让人以为日志是安全的.
_SENSITIVE_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
)

_REDACTED = "***"


class _ChatVaultHandler(logging.StreamHandler):
    """标记本模块安装的处理器

    重复配置时只移除自己安装的处理器, 保留宿主进程 (例如测试收集器) 添加的
    处理器, 这样本模块被嵌入到别的进程里也不会破坏宿主的日志设置.
    """


def _is_sensitive(field_name: str) -> bool:
    """判断字段名是否疑似敏感"""

    lowered = field_name.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """取出调用方通过 ``extra`` 传入的结构化字段

    过滤掉 logging 自身的属性后, 剩下的就是调用方附加的业务字段. 调用方因此
    不需要把字段塞进某个约定的嵌套名字, 按常规写法传即可.
    """

    fields: dict[str, Any] = {}
    for name, value in record.__dict__.items():
        if name in _STANDARD_RECORD_ATTRIBUTES or name.startswith("_"):
            continue
        fields[name] = _REDACTED if _is_sensitive(name) else value
    return fields


def _timestamp(record: logging.LogRecord) -> str:
    """按 UTC 生成毫秒精度的时间戳

    统一用 UTC 而不是本地时间: 日志经常要跨机器比对, 本地时区会带来歧义.
    """

    moment = datetime.fromtimestamp(record.created, tz=timezone.utc)
    return moment.isoformat(timespec="milliseconds")


class TextFormatter(logging.Formatter):
    """面向终端的行式格式

    形如
    ``2024-01-01T00:00:00.000+00:00 INFO    modules.services.importing 导入完成 batch_id='b1'``.
    结构化字段追加在消息之后, 人眼扫读时看前半段即可.
    """

    def format(self, record: logging.LogRecord) -> str:
        line = (
            f"{_timestamp(record)} {record.levelname:<7} "
            f"{record.name} {record.getMessage()}"
        )

        fields = _extra_fields(record)
        if fields:
            rendered = " ".join(f"{name}={value!r}" for name, value in fields.items())
            line = f"{line} {rendered}"

        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"

        if record.stack_info:
            line = f"{line}\n{self.formatStack(record.stack_info)}"

        return line


class JsonFormatter(logging.Formatter):
    """面向日志收集系统的单行 JSON 格式

    每行一个完整 JSON 对象, 结构化字段保持独立, 便于检索而不是做文本解析.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": _timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        fields = _extra_fields(record)
        if fields:
            payload["fields"] = fields

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # ensure_ascii=False 保证中文提示可读, default=str 保证结构化字段里出现
        # Path, datetime 之类的对象时不会因为无法序列化而丢掉整条日志
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    level: int | str = logging.INFO,
    *,
    json_output: bool = False,
) -> None:
    """配置根日志器, 只应由进程入口调用

    重复调用不会叠加输出: 每次调用先移除本模块此前安装的处理器.

    参数:
        level: 最低输出级别, 可以是 ``"INFO"`` 这样的名字或 ``logging.INFO``
        json_output: 为真时输出单行 JSON, 适合交给日志收集系统; 为假时输出
            给人看的行式文本

    Raises:
        ValueError: level 是无法识别的级别名时抛出. 这属于启动配置错误,
            应当立刻失败, 而不是悄悄退回某个默认级别
    """

    if isinstance(level, str):
        resolved = logging.getLevelNamesMapping().get(level.upper())
        if resolved is None:
            raise ValueError(f"无法识别的日志级别: {level!r}")
        level = resolved

    root = logging.getLogger()

    for handler in list(root.handlers):
        if isinstance(handler, _ChatVaultHandler):
            root.removeHandler(handler)
            handler.close()

    handler = _ChatVaultHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_output else TextFormatter())

    root.addHandler(handler)

    # 已知取舍: 这里设置的是根日志器的级别, 而不是本处理器自己的级别.
    # 副作用是传入 DEBUG 会同时放开第三方库 (uvicorn, httpx 等) 的日志,
    # 传入 WARNING 则会压掉它们的 INFO. 当前只有进程入口调用本函数, 此时
    # "入口决定全局级别" 正是期望行为, 因此保留. 若将来有库代码或测试调用,
    # 需要改为给 handler 设级别, 代价是失去 "DEBUG 能看到第三方库日志" 这一点.
    root.setLevel(level)

