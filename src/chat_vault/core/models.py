"""
整个程序使用的核心模型，但不涉及具体实现。
"""

from dataclasses import dataclass, field
from datetime import datetime


# ============ 内容域 ============


@dataclass
class Conversation:
    """对话类，代表一次完整的对话，包括主链和分支。"""

    source_id: str                                  # 备份包内唯一标识
    title: str
    raw_data: str

    source_type: str = "chatbox"                    # "chatbox" | "cherry studio" | "other"
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_published: bool = False
    import_batch: int | None = None                 # -> ImportRecord.id
    messages: list["Message"] = field(default_factory=list)
    branches: list["Branch"] = field(default_factory=list)

@dataclass
class Message:
    """消息模型类，表示一次对话中的一条消息。"""

    source_id: str
    role: str
    content: str                                    # 正文 Markdown
    thinking: str                                   # 思考内容
    position: int                                   # 主链或分支内的序号

    id: int | None = None
    conversation_id: int | None = None
    timestamp: datetime | None = None
    branch_id: int | None = None                    # None = 主链；非空 = 属于某分支
    metadata: dict = field(default_factory=dict)    # 模型名等扩展信息

@dataclass
class Branch:
    """分支模型类，表示一次对话中的一个分支。"""

    source_id: str
    index: int
    fork_message_source_id: str

    is_current: bool = False    
    id: int | None = None
    conversation_id: int | None = None
    messages: list[Message] = field(default_factory=list)

@dataclass
class Attachment:
    """附件模型类，表示一次对话中的一个附件。"""

    conversation_id: int
    attach_type: str                                # "image" | "file" | "other"  
    source_ref: str

    id: int | None = None
    display_name: str | None = None
    mime_type: str | None = None
    raw_data: str | None = None
    message_id: int | None = None
    display_index: int | None = None

@dataclass
class Comment:
    """评论模型类，表示一次对话中的一条评论。"""
    conversation_id: int
    content: str
    created_at: datetime

    is_deleted: bool = False                        # 管理员软删除
    nickname: str = "anonymous"
    message_id: int | None = None
    selection_start: int | None = None
    selection_end: int | None = None

@dataclass
class AdminMark:
    """管理员标记模型类，用于代表管理员用户对对话进行的标记。"""
    conversation_id: int
    message_id: int
    mark_type: str                                  # "highlight" | "delete" | "other"
    created_at: datetime
    created_by: int                                 # -> User.id


    is_deleted: bool = False                        # 管理员软删除
    note: str | None = None
    id: int | None = None



# ============ 管理域 ============

@dataclass
class User:
    """存储用户信息的模型类，包括普通用户和管理员。"""

    username: str
    password_hash: str                              # 禁止明文
    created_at: datetime
    id: int | None = None
    role: str = "admin"


# ============ 运维域 ============

@dataclass
class ImportRecord:
    """导入记录模型类，用于记录每次导入操作的详细信息。"""
    
    file_name: str
    file_hash: str                                  # 内容哈希，识别重复导入
    started_at: datetime
    status: str                                     # "success" | "partial" | "failed"
    total_count: int
    success_count: int
    failed_count: int

    source_type: str = "chatbox"                    # "chatbox" | "cherry studio" | "other"
    id: int | None = None
    error_summary: str | None = None
    finished_at: datetime | None = None
    
    
    

