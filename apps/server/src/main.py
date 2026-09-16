"""创建 Web 应用运行所需的依赖, 注册 API 路由与异常处理, 并提供 ASGI 应用入口

本模块是进程入口, 只做三件事: 读环境变量, 组装应用, 交给 ASGI 服务器.
业务逻辑一律不写在这里, 需要业务行为时应当落在 `modules/services` 并由路由调用.

启动顺序刻意固定为:

1. 配置日志. 必须先于其余步骤, 否则组装阶段出的问题不会被记录
2. 组装服务容器并建表. 容器创建失败时直接让启动失败, 不进入"能收请求但
   用不了"的半可用状态
3. 管理员自检. 库中一名管理员都没有且环境变量提供了初始凭据时自动建一名;
   凭据缺失则跳过, 这是"不启用自动初始化"的开关
4. 注册异常处理器. 必须在应用开始处理请求之前完成

退出顺序与启动相反: 关闭服务容器, 回滚未提交事务并断开数据库连接.

环境变量一览 (全部可选):

- ``CHAT_VAULT_DATABASE_PATH``: 数据库文件路径, 缺省时使用仓储层默认值
- ``CHAT_VAULT_ADMIN_USERNAME`` / ``CHAT_VAULT_ADMIN_PASSWORD``: 初始管理员凭据,
  两者必须同时提供才会生效; 缺少任意一项则跳过自动创建
- ``CHAT_VAULT_LOG_LEVEL``: 日志级别名, 例如 ``DEBUG``
- ``CHAT_VAULT_LOG_JSON``: 取 ``1`` / ``true`` / ``yes`` 时输出单行 JSON 日志
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from api.exception_handlers import register_exception_handlers
from api.routes import router
from bootstrap import ServiceContainer, ensure_initial_admin
from utils.logging import configure_logging

__all__ = ["app", "create_app", "main"]

logger = logging.getLogger(__name__)

DATABASE_PATH_ENV = "CHAT_VAULT_DATABASE_PATH"
ADMIN_USERNAME_ENV = "CHAT_VAULT_ADMIN_USERNAME"
ADMIN_PASSWORD_ENV = "CHAT_VAULT_ADMIN_PASSWORD"
LOG_LEVEL_ENV = "CHAT_VAULT_LOG_LEVEL"
LOG_JSON_ENV = "CHAT_VAULT_LOG_JSON"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _database_path() -> Path | None:
    """读取数据库路径

    空值返回 None 而不是空字符串, 让仓储层自己决定默认路径. 默认值只应有一处
    定义, 入口再抄一份就会在改默认时漏改.
    """

    raw = os.environ.get(DATABASE_PATH_ENV, "").strip()
    return Path(raw) if raw else None


def _json_logging_enabled() -> bool:
    """判断是否启用 JSON 日志输出"""

    return os.environ.get(LOG_JSON_ENV, "").strip().lower() in _TRUTHY


def _boot_admin(container: ServiceContainer) -> None:
    """启动时的管理员自检

    凭据不齐全时静默跳过: 这是正常部署方式之一 (由运维手工建管理员), 不应该
    在每次启动时都刷一条警告.

    用户名已被占用时只记一条错误并继续启动. 自动初始化是为了方便, 不是访问
    控制的强制环节; 为此让整个服务起不来, 代价大于收益. 运维能在日志里看到
    问题, 再用命令行重建管理员.
    """

    username = os.environ.get(ADMIN_USERNAME_ENV)
    password = os.environ.get(ADMIN_PASSWORD_ENV)

    if not username or not password:
        logger.debug("未提供初始管理员凭据, 跳过管理员自检")
        return

    try:
        created = ensure_initial_admin(container, username=username, password=password)
    except Exception:
        # 这里必须自己兜住: 管理员自检失败不应该阻止服务提供只读能力
        logger.exception("管理员自检失败, 服务将继续启动")
        return

    if created:
        logger.info("已在启动时创建初始管理员", extra={"username": username})
    else:
        logger.debug("库中已有管理员, 无需创建", extra={"username": username})


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """管理服务容器与数据库连接的生命周期

    用 lifespan 而不是已废弃的 ``on_event``: 容器需要在开始收请求之前就绪,
    并在停止收请求之后再关闭, 只有 lifespan 能表达这个边界.
    """

    container = ServiceContainer.create(database_path=_database_path())
    application.state.container = container
    logger.info(
        "服务容器已就绪",
        extra={"database_path": str(_database_path() or "默认路径")},
    )

    _boot_admin(container)

    try:
        yield
    finally:
        container.close()
        logger.info("服务容器已关闭")


def create_app() -> FastAPI:
    """组装并返回 ASGI 应用

    单独暴露成函数而不是只在模块顶层构造, 是为了让测试可以拿到一个全新的应用
    实例, 而不必复用模块级单例里已经建好的连接.

    日志在这里配置而不是只在 `main()` 里配置: 生产部署推荐由 ASGI 服务器直接
    加载本模块的 ``app`` 对象, 那条路径不会经过 `main()`. 配置函数是幂等的,
    重复调用只会按最后一次的参数重建自己的处理器.
    """

    configure_logging(
        os.environ.get(LOG_LEVEL_ENV, "INFO"),
        json_output=_json_logging_enabled(),
    )

    application = FastAPI(
        title="Chat Vault",
        description="Chatbox 对话备份的归档与浏览服务",
        lifespan=_lifespan,
    )

    # 路由留在 api/routes.py, 由它自己声明前缀和标签, 入口只负责挂载
    application.include_router(router)
    register_exception_handlers(application)

    return application


def main() -> None:
    """以开发模式启动 ASGI 服务器

    生产部署应当由 ASGI 服务器直接加载本模块的 ``app`` 对象, 而不是调用本函数:
    uvicorn 的 reload 和多进程管理需要它自己持有进程. 日志已经在 `create_app()`
    里配好, 这里不重复配置.
    """

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


app = create_app()


if __name__ == "__main__":
    main()
