"""管理数据库连接, 事务, 初始化流程和数据库运行配置"""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from core.exceptions import PersistenceError
from core.messages import MessageKey

# 默认数据库和数据库结构文件的位置
#
# 数据库路径以 pyproject.toml 所在目录为基准解析, 而不是以进程当前工作目录为
# 基准: 后者取决于从哪里启动程序, 从仓库根目录启动和从 apps/server 启动会
# 落到两个不同的库上, 数据看起来"丢了"其实只是找错了地方.
#
# 程序尚未成型, 数据库暂时生成在 data/raw 下, 完成后再迁回 data 下.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH = _PROJECT_ROOT / "data" / "raw" / "chat_vault.db"
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# 连接锁: 多个线程共用同一个连接时, 一个线程的 commit 会把另一个线程尚未
# 完成的事务一并提交, 回滚同理; 更直接的是, 两个线程同时在一个连接上执行
# 语句会让 sqlite3 抛出 InterfaceError. 因此连接上的每一次语句执行和事务
# 收尾都必须互斥. 锁是可重入的, 嵌套调用不会自锁. 这里用一把全局锁而不是
# 按连接分锁: 连接对象不支持弱引用, 也不允许附加属性, 按连接登记锁需要额外
# 的生命周期管理, 而本程序同时只使用一个连接, 全局锁的代价可以忽略
_CONNECTION_LOCK = threading.RLock()


class _MaterializedCursor(sqlite3.Cursor):
    """在语句执行完毕时就取走全部结果的游标

    游标本身不是线程安全的: 一个线程的 commit 会重置另一个线程尚未读完的
    游标, 使 fetchone 返回 None 或返回字段为空的残缺行, 并发执行语句还会
    直接抛出 InterfaceError. 只在 execute 上加锁挡不住这一点, 因为
    ``connection.execute(...).fetchone()`` 的 fetchone 发生在锁之外.

    这里把结果在 execute 期间一次性取出并缓存, 之后所有 fetch 都只读缓存,
    于是 ``connection.execute(...).fetchone()`` 整体成为原子操作, 仓储代码
    无需任何改动. 代价是结果集全量驻留内存, 本程序的查询规模远小于此.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        cursor: sqlite3.Cursor,
        rows: list[Any],
    ) -> None:
        # 已知问题: super().__init__() 会创建一个真实的 sqlite3 游标并向连接注册,
        # 而本类只借用它读取 description / rowcount / lastrowid, 之后不再使用,
        # 因此这个真实游标不会被 close(). 影响有限: 它只持有连接引用和少量状态,
        # 随本对象一起被回收; 连接关闭时 sqlite3 会隐式失效所有游标, 不会报错.
        # 若要消除, 可在读完三个属性后立刻 cursor.close(), 但当前没有实际收益.
        super().__init__(connection)
        self._rows = rows
        self._index = 0
        self._description = cursor.description
        self._rowcount = cursor.rowcount
        self._lastrowid = cursor.lastrowid


    @property
    def description(self):
        return self._description


    @property
    def rowcount(self):
        return self._rowcount


    @property
    def lastrowid(self):
        return self._lastrowid


    def fetchone(self):
        if self._index >= len(self._rows):
            return None

        row = self._rows[self._index]
        self._index += 1
        return row


    def fetchall(self):
        rows = self._rows[self._index:]
        self._index = len(self._rows)
        return rows


    def fetchmany(self, size: int | None = None):
        # 已知问题: 标准 sqlite3 游标在 size 为 None 时读 self.arraysize,
        # 而 arraysize 是可写属性(默认值恰好也是 1). 这里硬编码 1, 默认行为
        # 与标准游标一致, 但调用方设置 arraysize 后不会生效——本类没有覆写
        # arraysize, 于是它可写却无效, 属于最坏的一种情况.
        # 当前全仓库没有任何地方调用 fetchmany 或设置 arraysize, 因此不构成
        # 实际缺陷. 将来若需要分页, 更合适的方向是给仓储层加显式的
        # limit / offset 参数, 而不是依赖游标的 fetchmany.
        if size is None:
            size = 1

        rows = self._rows[self._index : self._index + size]
        self._index += len(rows)
        return rows


    def __iter__(self):
        return iter(self.fetchall())


class _LockedConnection(sqlite3.Connection):
    """在每次语句执行和事务收尾时加锁的连接

    通过 ``sqlite3.connect(factory=...)`` 装配. 选择子类而不是在每个仓储里
    手动加锁: 仓储只持有连接对象, 逐个改仓储会漏掉新增的调用点, 而连接是
    所有数据库访问的唯一入口, 在这里加锁能覆盖全部路径.

    语句执行返回的是 _MaterializedCursor, 结果在锁内取完, 因此调用方在锁外
    继续 fetch 也是安全的.
    """

    def execute(self, *args, **kwargs):
        with _CONNECTION_LOCK:
            cursor = super().execute(*args, **kwargs)
            return _MaterializedCursor(self, cursor, cursor.fetchall())


    def executemany(self, *args, **kwargs):
        with _CONNECTION_LOCK:
            cursor = super().executemany(*args, **kwargs)
            return _MaterializedCursor(self, cursor, cursor.fetchall())


    def executescript(self, *args, **kwargs):
        with _CONNECTION_LOCK:
            cursor = super().executescript(*args, **kwargs)
            return _MaterializedCursor(self, cursor, cursor.fetchall())


    def commit(self):
        with _CONNECTION_LOCK:
            return super().commit()


    def rollback(self):
        with _CONNECTION_LOCK:
            return super().rollback()


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

        # check_same_thread=False: 连接在 lifespan 所在线程创建, 而同步路由由
        # FastAPI 的线程池执行, 两者不是同一个线程. 跨线程使用本身是安全的
        # (sqlite3.threadsafety 为 3), 但多个线程共用同一个连接时, 一个线程的
        # commit 会提交另一个线程尚未完成的事务, 并发执行语句还会直接报错,
        # 因此连接上的访问必须串行化, 见 _LockedConnection
        connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
            factory=_LockedConnection,
        )
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

    注意: sqlite3 的 executescript() 在执行前会隐式提交当前未完成的事务,
    这是该模块的既定行为. 因此本函数禁止在 transaction() 内部调用, 否则外层
    事务会被静默提交, 回滚语义失效. 当前唯一调用点是 ServiceContainer.create(),
    调用时没有外层事务.

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
    """提供事务上下文, 成功提交, 异常时回滚

    事务之间互斥执行. 多个线程共用同一个连接时, 一个线程的 commit 会把另一个
    线程尚未完成的事务一并提交, 回滚同理, 因此整个事务期间都必须持有连接锁,
    只在单条语句上加锁不足以让事务保持原子. 锁是可重入的, 嵌套调用不会自锁.
    """

    with _CONNECTION_LOCK:
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
