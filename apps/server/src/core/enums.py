"""集中定义角色, 来源, 状态, 标记类型等跨模块共享的有限取值集合"""

from enum import Enum


class UserRole(str, Enum):
    """用户角色"""

    ADMIN = "admin"
    USER = "user"


class MessageRole(str, Enum):
    """消息在所属消息链中承担的角色"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SourceType(str, Enum):
    """对话内容的来源格式

    取值一律使用不含空白的短横杠形式: 来源类型会作为来源标识的命名空间前缀
    (见 `modules/adapters/preprocess.py`), 而命名空间校验拒绝任何含空白的
    前缀. 用 "cherry studio" 这类带空格的名字会让该来源的标识全部无法通过
    校验, 因此这里统一用 "cherry-studio".
    """

    CHATBOX = "chatbox"
    CHERRY_STUDIO = "cherry-studio"
    OTHER = "other"


class AttachmentType(str, Enum):
    """附件承载的资源类型"""

    IMAGE = "image"
    FILE = "file"
    OTHER = "other"


class CommentTarget(str, Enum):
    """评论挂载的目标对象"""

    CONVERSATION = "conversation"
    MESSAGE = "message"


class MarkType(str, Enum):
    """管理员标记的类型"""

    HIGHLIGHT = "highlight"
    PIN = "pin"
    OTHER = "other"


class ImportStatus(str, Enum):
    """导入批次的最终状态

    只有成功和失败两档. 曾经存在过"部分成功", 但它把"这次导入到底算不算数"
    变成了一个需要调用方二次判断的问题: 批次落库了, 一部分内容也落库了,
    调用方却无法据此决定要不要重试. 现在一次导入要么整体成立, 要么整体不成立,
    单条解析失败只记进 `error_summary`, 不影响批次状态.
    """

    SUCCESS = "success"
    FAILED = "failed"