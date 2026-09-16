"""提示文本台账与业务异常体系的行为检查

覆盖四件事:
- 文本目录与键集合完全对应: 每个键都有文案, 没有多余的文案条目
- 没有失效的键: 源码里确实引用了每个键, 不存在"定义了却没人用"的遗留项
- 异常体系可按类型被捕捉, 且仍能满足既有的内置异常捕获写法
- 文案里的占位符与抛出点传入的参数一致
"""

import ast
import re
from pathlib import Path

import pytest

from core.exceptions import (
    ChatVaultError,
    ConflictError,
    ImportFailedError,
    NotAuthenticatedError,
    NotFoundError,
    PermissionDeniedError,
    PersistenceError,
    ValidationError,
)
from core.messages import TEXTS, MessageKey, placeholders, render

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "apps" / "server" / "src"

# 目录自身所在的文件不参与"键是否被引用"的统计: 那里出现的是键的定义
CATALOG_MODULE = SOURCE_ROOT / "core" / "messages.py"


def _iter_source_files() -> list[Path]:
    """列出全部源码文件"""

    return sorted(path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)


def _referenced_message_keys() -> set[str]:
    """静态扫描源码, 收集被引用的 MessageKey 成员名

    用语法树而不是正则: 正则会被注释和字符串里的同名文字骗到, 而且分不清
    ``MessageKey.USER_NOT_FOUND`` 和恰好同名的局部变量.
    """

    referenced: set[str] = set()

    for path in _iter_source_files():
        if path == CATALOG_MODULE:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if node.value.id == "MessageKey":
                referenced.add(node.attr)

    return referenced


def test_every_key_has_text() -> None:
    """每个键都必须有对应文案

    缺失的键会在抛出时才炸, 而且炸在执行路径上; 这里让它在测试阶段就暴露.
    """

    missing = [key.name for key in MessageKey if key not in TEXTS]
    assert missing == []


def test_catalog_has_no_unused_entries() -> None:
    """目录里不能有非 MessageKey 的键

    目录用 MessageKey 做键, 因此多出条目的唯一可能就是有人写了裸字符串.
    """

    stray = [key for key in TEXTS if not isinstance(key, MessageKey)]
    assert stray == []


def test_catalog_has_no_duplicate_text() -> None:
    """同一批语义不应重复登记同一句文案

    重复文案通常意味着两个键其实是一件事, 应该合并成一个键. 例外情况是
    两个不同语义恰好措辞相同, 此时应当主动区分措辞.
    """

    seen: dict[str, MessageKey] = {}
    duplicates: list[tuple[str, str]] = []

    for key, text in TEXTS.items():
        previous = seen.get(text)
        if previous is not None:
            duplicates.append((previous.name, key.name))
        else:
            seen[text] = key

    assert duplicates == []


def test_no_dead_keys() -> None:
    """每个键都必须真的被源码引用

    这是这套设计的核心收益: 文本集中之后, 失效的键会悄悄堆积. 用语法树扫描
    让"删掉了抛出点却忘了删文案"变成一条测试失败, 而不是半年后才发现的垃圾.
    """

    referenced = _referenced_message_keys()
    declared = {key.name for key in MessageKey}

    dead = sorted(declared - referenced)
    assert dead == [], f"以下键定义了但没有任何抛出点引用: {dead}"


def test_referenced_keys_all_exist() -> None:
    """源码引用的键必须都在枚举里

    这条方向与上一条相反, 用来抓"引用了拼错的键名". 类型检查通常也能发现,
    但静态扫描不依赖类型检查工具是否跑过.
    """

    referenced = _referenced_message_keys()
    declared = {key.name for key in MessageKey}

    unknown = sorted(referenced - declared)
    assert unknown == [], f"以下键被引用但未定义: {unknown}"


def test_render_returns_template_without_params() -> None:
    """无占位符的键直接返回文案本身"""

    assert render(MessageKey.ADMIN_REQUIRED) == TEXTS[MessageKey.ADMIN_REQUIRED]


# 连续三个以上问号极不可能是正常中文文案, 出现即说明这条文本被编码转换损坏过
_LOST_TEXT = re.compile(r"\?{3,}")


@pytest.mark.parametrize("key", list(MessageKey), ids=lambda key: key.name)
def test_text_is_not_corrupted(key: MessageKey) -> None:
    """文案不能是被编码转换损坏过的残留

    中文在缺少编码声明的管道里会被替换成问号, UTF-8 被按单字节解码则会留下
    替换字符. 这两种损坏都不会让程序报错, 只会让用户看到一串问号或乱码,
    因此必须由测试兜住. 历史上一度有两条文案因此变成纯问号并被提交,
    这个用例就是为了让同类问题不再有机会通过.
    """

    text = TEXTS[key]

    assert text.strip(), f"{key.name} 的文案为空"
    assert not _LOST_TEXT.search(text), f"{key.name} 的文案疑似编码损坏: {text!r}"
    assert "\ufffd" not in text, f"{key.name} 的文案含替换字符: {text!r}"


def test_render_fills_placeholders() -> None:
    """带占位符的键按参数填充"""

    rendered = render(MessageKey.USER_NOT_FOUND, user_id=7)
    assert rendered == TEXTS[MessageKey.USER_NOT_FOUND].format(user_id=7)
    assert "7" in rendered


def test_render_rejects_unknown_key() -> None:
    """键不在目录里时抛出 KeyError

    这属于编程错误, 不应该被静默吞掉退化成空字符串.
    """

    with pytest.raises(KeyError):
        render("not_a_real_key")  # type: ignore[arg-type]


def test_placeholders_reports_named_fields() -> None:
    """占位符读取能列出一个键需要的参数名"""

    assert placeholders(MessageKey.ADMIN_REQUIRED) == ()
    assert placeholders(MessageKey.USERNAME_ALREADY_EXISTS) == ("username",)


@pytest.mark.parametrize(
    "key",
    [
        MessageKey.USERNAME_ALREADY_EXISTS,
        MessageKey.USER_NOT_FOUND,
        MessageKey.CONVERSATION_NOT_FOUND,
        MessageKey.MESSAGE_NOT_FOUND,
        MessageKey.MESSAGE_OWNER_CONVERSATION_NOT_FOUND,
        MessageKey.CONVERSATION_BRANCH_ANCHOR_MISSING,
        MessageKey.BRANCH_SOURCE_ID_DUPLICATED,
        MessageKey.BRANCH_NOT_FOUND,
        MessageKey.MESSAGE_SOURCE_ID_DUPLICATED,
        MessageKey.MESSAGE_POSITION_DUPLICATED,
        MessageKey.MESSAGE_ROLE_UNSUPPORTED,
        MessageKey.MESSAGE_ATTACHMENT_ANCHOR_MISSING,
        MessageKey.ATTACHMENT_MESSAGE_MISMATCH,
        MessageKey.ATTACHMENT_TYPE_UNSUPPORTED,
        MessageKey.IMPORT_FILE_NOT_FOUND,
        MessageKey.IMPORT_PATH_NOT_FILE,
        MessageKey.IMPORT_FORMAT_MISMATCH,
        MessageKey.SOURCE_NAMESPACE_SEPARATOR,
        MessageKey.DATABASE_CONNECTION_FAILED,
        MessageKey.DATABASE_INITIALIZATION_FAILED,
    ],
)
def test_placeholder_keys_render_with_their_own_names(key: MessageKey) -> None:
    """需要参数的键, 用自己声明的占位符名可以渲染成功

    参数名写错时 ``str.format`` 会抛 KeyError, 这条测试把"文案和抛出点用了
    不同参数名"这类错误挡在测试阶段. 填充值本身带尖括号, 因此渲染后如果
    还残留花括号, 就说明有占位符没被替换掉.
    """

    params = {name: f"<{name}>" for name in placeholders(key)}
    rendered = render(key, **params)

    assert "{" not in rendered
    for name in params:
        assert f"<{name}>" in rendered


def test_business_error_requires_message_key() -> None:
    """业务异常必须携带键, 不能内联文案

    这是防止文案重新散回实现的最后一道闸门.
    """

    with pytest.raises(TypeError):
        ChatVaultError("对话不存在")  # type: ignore[arg-type]


def test_business_error_exposes_key_and_params() -> None:
    """异常对象保留键和参数, 出口层据此翻译而不是解析文案"""

    error = NotFoundError(MessageKey.USER_NOT_FOUND, user_id=3)

    assert error.key is MessageKey.USER_NOT_FOUND
    assert error.params == {"user_id": 3}
    assert str(error) == render(MessageKey.USER_NOT_FOUND, user_id=3)


@pytest.mark.parametrize(
    ("error_type", "builtin_type"),
    [
        (ValidationError, ValueError),
        (ConflictError, ValueError),
        (ImportFailedError, ValueError),
        (NotFoundError, LookupError),
        (NotAuthenticatedError, PermissionError),
        (PermissionDeniedError, PermissionError),
        (PersistenceError, RuntimeError),
    ],
)
def test_errors_are_still_catchable_as_builtins(
    error_type: type[ChatVaultError],
    builtin_type: type[Exception],
) -> None:
    """业务异常同时是内置异常, 既有捕获写法继续成立

    这让迁移可以逐步进行: 尚未改成捕捉业务异常的调用点不会因为换了异常类型
    而漏接, 从"全都抛内置异常"到"全都抛业务异常"之间没有断点.
    """

    error = error_type(MessageKey.CONVERSATION_NOT_FOUND, conversation_source_id="c1")

    assert isinstance(error, builtin_type)
    assert isinstance(error, ChatVaultError)


def test_all_business_errors_share_the_base() -> None:
    """所有业务异常都能被基类一次接住

    出口层因此只需要注册一个处理器, 新加异常类不必再改注册代码.
    """

    for error_type in (
        ValidationError,
        NotFoundError,
        ConflictError,
        NotAuthenticatedError,
        PermissionDeniedError,
        ImportFailedError,
        PersistenceError,
    ):
        error = error_type(MessageKey.ADMIN_REQUIRED)
        assert isinstance(error, ChatVaultError)