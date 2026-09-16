"""集中定义导入, 查询, 权限, 校验和持久化流程使用的业务异常体系

异常只携带"提示键 + 格式化参数", 不携带拼好的文案. 同一件事在不同出口
(HTTP 响应, 命令行输出, 日志)可能需要不同表述, 提前把文案拼死在异常里就
失去了这个余地. 文本本身集中在 `core.messages`, 这里只负责分类.

分类的依据是**调用方要做什么**, 而不是"哪里出了问题". 只有当调用方对两种
错误的处理方式确实不同时才拆成两个类, 否则用同一个类加不同的键即可.

这些类同时继承对应的内置异常, 因此 `except ValueError` 之类的既有写法仍然
成立, 迁移可以逐步进行, 不必一次性改完所有捕获点.

分层约定:
- 只在服务和仓储层抛出, 接口层和适配层不抛业务异常
- `api` 和 `cli` 只做翻译: 类型到响应状态或退出码, 不判断文案
- 不把 HTTP 状态码写进本模块, 那是出口层的事
"""

from core.messages import MessageKey, render

__all__ = [
    "ChatVaultError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "NotAuthenticatedError",
    "PermissionDeniedError",
    "ImportFailedError",
    "PersistenceError",
]


class ChatVaultError(Exception):
    """业务异常基类

    `key` 指出这是什么错误, `params` 提供文案占位符的取值. `str()` 仍然给出
    可读文本, 作为日志和调试时的兜底.

    刻意不接受裸字符串: 内联文案正是本设计要消除的东西, 让它在构造时就失败
    比让它悄悄混回代码里更好.
    """

    def __init__(self, key: MessageKey, **params: object) -> None:
        if not isinstance(key, MessageKey):
            raise TypeError(f"业务异常必须携带 MessageKey, 不能内联文案: {key!r}")

        self.key = key
        self.params = params

        # args 与 str() 保持一致, 便于日志, repr 和测试断言直接读取
        self.args = (render(key, **params),)

    def __str__(self) -> str:
        return str(self.args[0])


class ValidationError(ChatVaultError, ValueError):
    """输入内容不符合业务规则

    例如字段为空, 序号为负, 结构关系矛盾. 属于调用方给错了数据,
    修正后重新提交就可能成功.
    """


class NotFoundError(ChatVaultError, LookupError):
    """按标识查找目标, 但目标不存在

    例如对话, 消息, 分支, 用户不存在.
    """


class ConflictError(ChatVaultError, ValueError):
    """输入内容与库中既有数据冲突

    与 `ValidationError` 的区别是: 校验失败只跟输入自身有关, 换一份输入
    仍然可以; 冲突必须查看当前状态后由人决定怎么处理, 例如改个名字.
    """


class NotAuthenticatedError(ChatVaultError, PermissionError):
    """操作需要登录身份, 但当前调用没有身份

    与 `PermissionDeniedError` 分开, 是因为出口层的处理不同: 前者是
    "请先登录", 后者是"你登录了但不够格", 引导用户做的事不一样.
    """


class PermissionDeniedError(ChatVaultError, PermissionError):
    """当前身份明确, 但没有执行该操作的权限"""


class ImportFailedError(ChatVaultError, ValueError):
    """整批导入无法启动

    用于导入开始前的整体性问题, 例如路径不是文件, 文件格式与适配器不符.
    单条对话的内容问题属于 `ValidationError`, 由导入流程记录到批次错误里,
    不会中断整批导入.
    """


class PersistenceError(ChatVaultError, RuntimeError):
    """数据库连接的建立, 结构初始化或语句执行失败

    属于环境或数据层面的故障, 不是调用方的输入问题, 调用方通常无法补救.
    """
