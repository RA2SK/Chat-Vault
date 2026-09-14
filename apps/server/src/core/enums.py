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
    """对话内容的来源格式"""

    CHATBOX = "chatbox"
    CHERRY_STUDIO = "cherry studio"
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
    """导入批次的最终状态"""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"