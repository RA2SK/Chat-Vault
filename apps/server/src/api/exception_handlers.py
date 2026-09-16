"""将业务异常和系统异常转换为统一的前端错误响应

本模块是异常体系唯一的翻译点. 上游只负责按语义抛异常, 这里负责把语义映射成
HTTP 状态码和响应体, 因此 "哪个错误对应哪个状态码" 只有一处需要维护.

刻意不做的事情:

- 不按文案判断错误种类. 文案随时会改, 靠文案分支的代码改一次文案就会失效.
  分支一律看异常类型和 `key`
- 不在业务层写状态码. 业务层不知道 HTTP 的存在, 这是它能被命令行复用的前提
- 不把内部异常的原文回给前端. 未预期的异常一律返回通用提示, 细节只进日志,
  避免把数据库结构, 文件路径之类的内部信息暴露出去
- 不重复记录日志. 业务异常是预期内的结果, 用 ``warning`` 记一条即可; 未预期
  的异常才用 ``exception`` 连同堆栈记下来, 且只在这里记一次
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
from core.messages import MessageKey, render

__all__ = ["register_exception_handlers"]

logger = logging.getLogger(__name__)

# 业务异常类型到 HTTP 状态码的映射
# 子类放在父类之前没有意义, 这里的类型之间没有继承关系, 查表即可
_STATUS_CODES: dict[type[ChatVaultError], int] = {
    ValidationError: 400,
    NotAuthenticatedError: 401,
    PermissionDeniedError: 403,
    NotFoundError: 404,
    ConflictError: 409,
    ImportFailedError: 422,
    PersistenceError: 500,
}

# 未预期异常的固定提示. 不回传原始异常文本, 避免泄露内部细节
_INTERNAL_ERROR_MESSAGE = "服务器内部错误"


def _status_for(error: ChatVaultError) -> int:
    """查业务异常对应的状态码

    用精确类型查表, 而不是 ``isinstance`` 逐项判断: 查表让 "一个类型漏配状态码"
    这种错误在测试里立刻暴露, 而 isinstance 会悄悄退回到某个父类的状态码.

    查不到时退回 500, 因为这属于本模块的配置遗漏, 不是调用方的问题.
    """

    return _STATUS_CODES.get(type(error), 500)


def _error_response(status_code: int, message: str, key: str) -> JSONResponse:
    """构造统一形状的错误响应

    同时给出 ``message`` 和 ``key``: 前者供人直接展示, 后者供前端做分支判断.
    前端靠稳定的键而不是文案来区分错误, 文案改动才不会波及前端.
    """

    return JSONResponse(
        status_code=status_code,
        content={"error": {"key": key, "message": message}},
    )


async def handle_chat_vault_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """把业务异常转换成错误响应"""

    assert isinstance(exc, ChatVaultError)

    status_code = _status_for(exc)
    message = str(exc)

    # 5xx 说明是环境或数据层面的故障, 需要开发者关注, 记 warning 并带上堆栈;
    # 4xx 是调用方的输入或权限问题, 属于正常业务结果, 只记一条简短记录
    if status_code >= 500:
        logger.warning(
            "业务异常导致请求失败",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "key": exc.key.value,
                "params": exc.params,
            },
            exc_info=exc,
        )
    else:
        logger.info(
            "请求被业务规则拒绝",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "key": exc.key.value,
            },
        )

    return _error_response(status_code, message, exc.key.value)


async def handle_unexpected_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """把未预期异常转换成通用错误响应

    这是全应用唯一用 ``logger.exception`` 记录堆栈的地方. 中间层原样抛出,
    不重复记录, 同一个故障因此只会在日志里出现一次.
    """

    logger.exception(
        "请求处理时发生未预期异常",
        extra={
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(500, _INTERNAL_ERROR_MESSAGE, "internal_error")


async def handle_request_validation_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """把请求参数校验失败转换成统一形状的错误响应

    FastAPI 自带的校验失败响应是 ``{"detail": [...]}``, 与业务异常的
    ``{"error": {...}}`` 形状不同. 前端如果只按一种形状解析, 就会在参数写错
    时拿到一个解析不了的结构, 因此这里把它翻译成同一种形状.

    校验细节会被拼进文案: 这些信息描述的是调用方自己发来的参数, 不涉及内部
    结构, 回传出去不会泄露什么, 反而能让调用方直接看出哪个参数写错了.
    """

    assert isinstance(exc, RequestValidationError)

    detail = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )

    logger.info(
        "请求参数校验失败",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": 422,
            "key": MessageKey.REQUEST_INVALID.value,
        },
    )

    return _error_response(
        422,
        render(MessageKey.REQUEST_INVALID, detail=detail),
        MessageKey.REQUEST_INVALID.value,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """把异常处理器注册到应用

    ``Exception`` 的处理器在 Starlette 中默认会被 ServerErrorMiddleware 接走
    并重新抛出, 这里显式注册是为了让响应形状与业务异常保持一致.
    """

    app.add_exception_handler(ChatVaultError, handle_chat_vault_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
