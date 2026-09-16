"""管理数据库连接, 事务, 初始化流程和数据库运行配置"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# 默认数据库和数据库结构文件的位置
# 程序尚未成型, 数据库暂时生成在 data/raw 下, 完成后再迁回 data 下
DEFAULT_DATABASE_PATH = Path("data/raw/chat_vault.db")
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_connection(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> sqlite3.Connection:
    """创建并配置一个 SQLite 数据库连接"""

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    
    return connection


def initialize_database(
    connection: sqlite3.Connection,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> None:
    """执行 schema.sql, 初始化数据库结构"""

    schema_sql = schema_path.read_text(encoding="utf-8-sig")
    connection.executescript(schema_sql)


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


