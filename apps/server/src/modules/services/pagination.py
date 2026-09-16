"""分页窗口的业务策略

窗口大小是业务规则而不是传输细节, 因此默认值和上限钳制放在服务层:
接口层只负责把查询参数解析成整数, 不应该自己决定"最多 200 条"这种策略,
否则命令行层和 Web 层会各自维护一份不同的上限.

`normalize_page` 是唯一允许把外部传入的原始整数变成 `Page` 的地方.
"""

from core.pagination import Page

__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "normalize_page"]

DEFAULT_PAGE_SIZE = 50

# 上限存在的意义不是"防止前端要太多", 而是给单次响应体一个可预测的上界.
# 归档场景下 200 条对话摘要约 30 KB, 是一个前端可以一次性渲染的量级.
MAX_PAGE_SIZE = 200


def normalize_page(limit: int | None, offset: int | None = None) -> Page:
    """把外部传入的分页参数收敛成一个合法窗口

    limit 为 None 时取默认值; 超出上限时钳到上限而不是报错, 因为"要多了"
    是调用方的意图表达, 不是错误. 小于 1 的值同样钳到 1, 避免出现
    LIMIT 0 这种"永远返回空页"的窗口.
    """

    resolved_limit = DEFAULT_PAGE_SIZE if limit is None else limit
    resolved_limit = max(1, min(resolved_limit, MAX_PAGE_SIZE))
    resolved_offset = max(0, offset or 0)

    return Page(limit=resolved_limit, offset=resolved_offset)
