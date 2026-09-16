"""解析命令行参数, 创建应用依赖, 调用业务服务并将业务结果转换为终端输出与退出码

本模块是命令行入口, 与 `main.py` 一样只做编排: 读参数, 组装容器, 调服务,
把结果或异常翻译成终端能看的东西. 业务逻辑一律不写在这里.

两条输出通道刻意分开:

- 命令结果走标准输出. 用户可能会把它重定向到文件或交给别的程序处理
- 日志与错误走标准错误. 这样 "把结果管道给下一个命令" 不会把日志混进数据里

业务异常的文本直接打印, 不经过日志器: 用户看的是 "对话 xx 不存在" 这句话,
而不是一行带时间戳和级别的日志. 日志只记录开发者需要的东西.

退出码约定 (供脚本判断失败原因):

- 0 成功
- 1 未预期异常
- 2 命令行用法错误 (由 argparse 产生)
- 3 输入或导入内容不合法
- 4 目标不存在
- 5 与库中既有数据冲突
- 6 需要登录
- 7 权限不足
- 8 持久化故障
"""

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from bootstrap import ServiceContainer
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
from core.messages import MessageKey
from core.pagination import Page, PageResult
from modules.adapters import REGISTRY, detect_importer, resolve_importer
from modules.services.pagination import MAX_PAGE_SIZE
from utils.logging import configure_logging

__all__ = ["main"]

logger = logging.getLogger(__name__)

LOG_LEVEL_ENV = "CHAT_VAULT_LOG_LEVEL"
LOG_JSON_ENV = "CHAT_VAULT_LOG_JSON"
PASSWORD_ENV = "CHAT_VAULT_ADMIN_PASSWORD"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# 业务异常类型到退出码的映射. 用精确类型查表, 与 api 层的状态码映射同构:
# 漏配一项会被测试发现, 而不是悄悄退回到父类的退出码
_EXIT_CODES: dict[type[ChatVaultError], int] = {
    ValidationError: 3,
    ImportFailedError: 3,
    NotFoundError: 4,
    ConflictError: 5,
    NotAuthenticatedError: 6,
    PermissionDeniedError: 7,
    PersistenceError: 8,
}

_EXIT_UNEXPECTED = 1


def _build_parser() -> argparse.ArgumentParser:
    """构造参数解析器"""

    parser = argparse.ArgumentParser(
        prog="chat-vault",
        description="Chatbox 对话备份的归档与浏览命令行工具",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="数据库文件路径, 缺省时使用程序默认路径",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出调试级别日志",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="导入一个备份文件")
    import_parser.add_argument("path", type=Path, help="备份文件路径")
    import_parser.add_argument(
        "--format",
        dest="format_key",
        default=None,
        choices=sorted(REGISTRY),
        help="指定输入格式, 缺省时按顺序尝试所有已注册适配器",
    )

    conversations_parser = subparsers.add_parser("conversations", help="列出对话")
    conversations_parser.add_argument(
        "--published",
        action="store_true",
        help="只列出已发布的对话",
    )

    show_parser = subparsers.add_parser("show", help="查看一个对话的分支与消息概览")
    show_parser.add_argument("source_id", help="对话的来源标识")

    comments_parser = subparsers.add_parser(
        "comments",
        help="列出某个对话下的全部评论, 含其消息下的评论",
    )
    comments_parser.add_argument("source_id", help="对话的来源标识")

    admin_parser = subparsers.add_parser("create-admin", help="创建一个管理员账号")
    admin_parser.add_argument("username", help="管理员用户名")
    admin_parser.add_argument(
        "--password-env",
        default=PASSWORD_ENV,
        help=(
            "从该环境变量读取密码, 缺省为 "
            f"{PASSWORD_ENV}; 该变量为空时改为交互式输入"
        ),
    )

    return parser


def _run_import(container: ServiceContainer, args: argparse.Namespace) -> int:
    """执行导入命令"""

    if args.format_key is not None:
        importer = resolve_importer(args.format_key)
    else:
        importer = detect_importer(args.path)

    batch = container.import_service.import_file(args.path, importer)

    print(f"批次标识: {batch.id}")
    print(f"文件: {batch.file_name}")
    print(f"格式: {batch.format_key}")
    print(f"状态: {batch.status.value}")
    print(
        f"条目: 共 {batch.total_count}, "
        f"成功 {batch.success_count}, "
        f"失败 {batch.failed_count}"
    )

    if batch.error_summary:
        print(f"问题摘要: {batch.error_summary}")

    return 0


def _collect_all(fetch_page: Callable[[Page], PageResult[Any]]) -> list[Any]:
    """逐页取完一个分页接口的全部结果

    接口契约里没有"不分页"这条路径, 这是刻意的: 一旦存在, 未加限制的查询就会
    从某个调用点悄悄溜回架构里. 命令行确实需要看全部数据, 但那是操作者在自己
    终端上的明确意图, 所以由这里显式循环取完, 而不是让契约开一个后门.

    循环按 offset 递增, 直到某一页返回 has_more 为假. 这里不假设"返回条数少于
    limit 就是最后一页", 因为最后一页刚好填满时那个判据是错的.
    """

    items: list[Any] = []
    offset = 0

    while True:
        result = fetch_page(Page(limit=MAX_PAGE_SIZE, offset=offset))
        items.extend(result.items)

        if not result.has_more:
            return items

        offset += len(result.items)


def _run_conversations(container: ServiceContainer, args: argparse.Namespace) -> int:
    """执行列出对话命令"""

    if args.published:
        conversations = _collect_all(
            lambda page: container.query_service.list_published_conversations(page)
        )
    else:
        conversations = _collect_all(
            lambda page: container.query_service.list_conversations(page)
        )

    if not conversations:
        print("没有符合条件的对话")
        return 0

    for conversation in conversations:
        marker = "已发布" if conversation.is_published else "未发布"
        print(f"{conversation.source_id}\t{marker}\t{conversation.title}")

    return 0


def _run_show(container: ServiceContainer, args: argparse.Namespace) -> int:
    """执行查看对话概览命令"""

    detail = container.query_service.get_conversation_detail(args.source_id)

    if detail is None:
        raise NotFoundError(
            MessageKey.CONVERSATION_NOT_FOUND,
            conversation_source_id=args.source_id,
        )

    conversation = detail.conversation
    print(f"对话: {conversation.title}")
    print(f"来源标识: {conversation.source_id}")
    print(f"分支数: {len(detail.branches)}")

    for branch in detail.branches:
        messages = detail.messages.get(branch.source_id, [])
        attachment_count = sum(
            len(detail.attachments.get(message.source_id, [])) for message in messages
        )
        print(
            f"  分支 {branch.index}: {branch.source_id} "
            f"消息 {len(messages)} 条, 附件 {attachment_count} 个"
        )

    return 0


def _run_comments(container: ServiceContainer, args: argparse.Namespace) -> int:
    """执行列出对话评论命令"""

    comments = _collect_all(
        lambda page: container.comment_service.list_by_conversation_including_messages(
            args.source_id, page
        )
    )

    if not comments:
        print("该对话下没有评论")
        return 0

    for comment in comments:
        print(f"{comment.created_at}\t{comment.nickname}\t{comment.content}")

    return 0


def _read_password(env_name: str) -> str:
    """从环境变量或交互式输入取得管理员密码

    刻意不提供 ``--password`` 参数: 命令行参数会进入 shell 历史记录和进程列表,
    密码因此会留在别人能读到的地方. 环境变量和交互式输入都没有这个问题.
    """

    from_env = os.environ.get(env_name, "")
    if from_env:
        return from_env

    return getpass.getpass("请输入管理员密码: ")


def _run_create_admin(container: ServiceContainer, args: argparse.Namespace) -> int:
    """执行创建管理员命令"""

    password = _read_password(args.password_env)
    user = container.user_service.register_admin(args.username, password)

    print(f"已创建管理员: {user.username}")
    print(f"用户标识: {user.id}")

    return 0


_HANDLERS = {
    "import": _run_import,
    "conversations": _run_conversations,
    "show": _run_show,
    "comments": _run_comments,
    "create-admin": _run_create_admin,
}


def _force_utf8_output() -> None:
    """把标准输出和标准错误切到 UTF-8

    默认编码取决于操作系统区域设置, 在中文提示上容易出现乱码或
    ``UnicodeEncodeError``. 命令行输出没有兼容旧编码的必要.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _exit_code_for(error: ChatVaultError) -> int:
    """查业务异常对应的退出码"""

    return _EXIT_CODES.get(type(error), _EXIT_UNEXPECTED)


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口, 返回进程退出码"""

    _force_utf8_output()

    parser = _build_parser()
    args = parser.parse_args(argv)

    configure_logging(
        "DEBUG" if args.verbose else os.environ.get(LOG_LEVEL_ENV, "INFO"),
        json_output=os.environ.get(LOG_JSON_ENV, "").strip().lower() in _TRUTHY,
    )

    container: ServiceContainer | None = None

    try:
        # 建库与建表也可能失败, 所以容器创建要放在 try 里面, 这样持久化故障
        # 也能走到统一的分支, 而不是从 main() 里抛出去变成一段堆栈
        container = ServiceContainer.create(database_path=args.database)

        handler = _HANDLERS[args.command]
        return handler(container, args)
    except ChatVaultError as error:
        # 业务异常是预期内的结果, 直接说人话, 不套日志格式. 键也打出来,
        # 因为脚本需要按稳定标识判断失败原因, 而不是去匹配会变的文案
        print(f"错误 [{error.key.value}]: {error}", file=sys.stderr)
        return _exit_code_for(error)
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return _EXIT_UNEXPECTED
    except Exception:
        # 出口层统一记录一次堆栈, 中间层不重复记录
        logger.exception("命令执行时发生未预期异常", extra={"command": args.command})
        print("发生了未预期的错误, 详情见日志", file=sys.stderr)
        return _EXIT_UNEXPECTED
    finally:
        if container is not None:
            container.close()


if __name__ == "__main__":
    sys.exit(main())
