"""管理数据库连接, 事务, 初始化流程和数据库运行配置"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from core.exceptions import PersistenceError
from core.messages import MessageKey

# 默认数据库和数据库结构文件的位置
# 程序尚未成型, 数据库暂时生成在 data/raw 下, 完成后再迁回 data 下
DEFAULT_DATABASE_PATH = Path("data/raw/chat_vault.db")
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_connection(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> sqlite3.Connection:
    """创建并配置一个 SQLite 数据库连接

    Raises:
        PersistenceError: 目录无法创建或数据库无法打开时抛出
    """

    try:
        database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    except (OSError, sqlite3.Error) as exc:
        raise PersistenceError(
            MessageKey.DATABASE_CONNECTION_FAILED,
            database_path=str(database_path),
            reason=str(exc),
        ) from exc

    return connection


def initialize_database(
    connection: sqlite3.Connection,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> None:
    """执行 schema.sql, 初始化数据库结构

    Raises:
        PersistenceError: 结构文件读取失败或 SQL 执行失败时抛出
    """

    try:
        schema_sql = schema_path.read_text(encoding="utf-8-sig")
        connection.executescript(schema_sql)
    except (OSError, sqlite3.Error) as exc:
        raise PersistenceError(
            MessageKey.DATABASE_INITIALIZATION_FAILED,
            schema_path=str(schema_path),
            reason=str(exc),
        ) from exc


@contextmanager
def transaction(
    connection: sqlite3.Connection,
) -> Generator[sqlite3.Connection, None, None]:
    """提供事务上下文, 成功提交, 异常时回滚"""

    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def close_connection(connection: sqlite3.Connection) -> None:
    """关闭数据库连接, 关闭前丢弃未提交的事务"""

    if connection.in_transaction:
        connection.rollback()

    connection.close()


