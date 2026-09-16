"""分页请求窗口与分页结果形状

这两个类型放在核心层, 因为它们描述的是"一次分页读取的输入和输出", 不依赖
任何一层: 仓储层用它表达 SQL 的 LIMIT/OFFSET, 服务层用它表达业务上的窗口
策略, 接口层用它表达契约签名, 接口层用它表达 HTTP 查询参数.

刻意不把分页参数做成"每个方法各自两个 int 参数": 那样每加一个可分页的方法
就要重复一遍 limit/offset 的校验和钳制逻辑, 而且调用方容易漏传其中一个.
"""

from dataclasses import dataclass, field
from typing import Generic, TypeVar

__all__ = ["Page", "PageResult"]

T = TypeVar("T")


@dataclass(frozen=True)
class Page:
    """一次分页请求的窗口

    ``limit`` 是本次最多返回多少条, ``offset`` 是跳过多少条. 两者都由服务层
    收敛成合法值之后再往下传, 仓储层因此可以假定它们已经合法.
    """

    limit: int
    offset: int = 0


@dataclass
class PageResult(Generic[T]):
    """一页数据, 附带"是否还有下一页"

    刻意不返回总数: 总数需要额外一次全表扫描, 而归档的总条数是一个没人会
    据此做决策的数字. ``has_more`` 由仓储层多取一行得到, 成本为零. 将来若
    前端确实需要总数, 增加 ``total`` 字段是纯增量改动, 不破坏现有形状.
    """

    items: list[T] = field(default_factory=list)
    has_more: bool = False
