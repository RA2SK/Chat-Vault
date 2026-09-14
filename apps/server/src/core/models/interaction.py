"""互动域模型, 描述用户在内容之上产生的操作记录

共同特点是需要挂靠在内容上, 记录操作者, 并允许管理员软删除或受限删除

互动域不使用内容图的 source_id 作为自身身份, 而是由应用侧生成 id,
对外引用内容时一律使用对方的 source_id
"""

from dataclasses import dataclass, field
from datetime import datetime

from core.enums import CommentTarget, MarkType
from core.types import AdminMarkId, CommentId, MessageRevisionId, UserId, new_id


@dataclass
class Comment:
    """评论模型, 表示用户对消息或对话的评论"""

    target_type: CommentTarget                      # "conversation" | "message"

    content: str
    created_at: datetime
    conversation_source_id: str | None = None       # target_type 为 conversation 时必填
    message_source_id: str | None = None            # target_type 为 message 时必填
    created_by: UserId | None = None
    nickname: str = "anonymous"

    id: CommentId = field(default_factory=lambda: CommentId(new_id()))
    is_deleted: bool = False                        # 管理员软删除


@dataclass
class AdminMark:
    """管理员标记模型, 用于代表管理员用户对消息进行的标记"""

    message_source_id: str                          # -> Message.source_id
    mark_type: MarkType                             # "highlight" | "pin" | "other"
    created_at: datetime
    created_by: UserId                              # -> User.id

    is_deleted: bool = False                        # 管理员软删除
    id: AdminMarkId = field(default_factory=lambda: AdminMarkId(new_id()))


@dataclass
class MessageRevision:
    """消息历史模型, 用于记录消息的编辑记录和迭代版本"""

    message_source_id: str                          # -> Message.source_id
    revision_no: int                                # 迭代版本
    content: str                                    # 本迭代的正文内容
    thinking: str                                   # 本迭代的思考内容
    created_at: datetime
    created_by: UserId
    reason: str | None = None                       # 管理员的修改备注
    id: MessageRevisionId = field(default_factory=lambda: MessageRevisionId(new_id()))
