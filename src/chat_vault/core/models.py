"""整个程序使用的核心模型, 但不涉及具体实现"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TypedDict

class Checksum(TypedDict):                          # 定义保存去重校验值的类型别名
    algorithm: str
    value: str

# ============ 内容域 ============

@dataclass
class Conversation:
    """对话模型, 代表一次完整的对话, 包括主链和消息级分支"""

    source_id: str                                  # 备份包内唯一标识, 幂等键
    title: str

    source_archive: str | None = None               # 原始备份文件在存档目录当中的文件名, 由 import_service 填写
    source_entry: str | None = None                 # 会话在原始备份文件内的相对路径, 由适配器填写
    source_type: str = "chatbox"                    # "chatbox" | "cherry studio" | "other"
    id: int | None = None
    created_at: datetime | None = None              # 由适配器根据首条消息计算
    updated_at: datetime | None = None              # 由适配器根据末条消息计算
    is_published: bool = False
    import_batch: int | None = None                 # -> ImportBatch.id
    messages: list["Message"] = field(default_factory=list)
    branches: list["Branch"] = field(default_factory=list)
    attachments: list["Attachment"] = field(default_factory=list)

@dataclass
class Message:
    """消息模型, 表示一次对话中的一条消息"""

    source_id: str                                  
    role: str                                       # "user" | "assistant" | "system"
    content: str                                    # 正文 Markdown, 已合并并清洗 text 片段
    position: int                                   # 在所属链中的序号

    thinking: str = ""                              # 思考链, 导入时清洗, 默认不展示
    model: str | None = None                        # 生成该消息的模型名
    id: int | None = None
    conversation_id: int | None = None
    timestamp: datetime | None = None
    branch_id: int | None = None                    # None = 主链；非空 = 属于某分支

@dataclass
class Branch:
    """分支模型, 仅表示消息级分支, 即 messageForksHash。"""

    source_id: str
    index: int
    fork_message_source_id: str

    is_current: bool = False    
    id: int | None = None
    conversation_id: int | None = None
    messages: list[Message] = field(default_factory=list)

@dataclass
class Attachment:
    """附件模型类, 表示一次对话中的一个附件"""

    attach_type: str                                # "image" | "file" | "other"
    source_ref: str                                 # 资源引用标识, 禁止绝对路径

    message_source_id: str | None = None            # 出现在哪条消息
    display_index: int | None = None                # 在该消息内的展示顺序

    display_name: str | None = None
    mime_type: str | None = None
    checksum: Checksum | None = None                # 资源去重
    size: int | None = None                         # 资源大小, 单位为字节

    id: int | None = None                           
    conversation_id: int | None = None              # 不在输入适配器处理, 由嵌套关系回填
    message_id: int | None = None                   # 不在输入适配器处理, 由 message_source_id 解析后回填

@dataclass
class Comment:
    """评论模型类, 表示一次对话中的一条评论 """
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
    """管理员标记模型类, 用于代表管理员用户对对话进行的标记"""
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
    """存储用户信息的模型类, 包括普通用户和管理员"""

    username: str
    password_hash: str                              # 禁止明文
    created_at: datetime
    id: int | None = None
    role: str = "admin"


# ============ 运维域 ============

@dataclass
class ImportBatch:
    """导入批次模型, 记录每次导入操作的结果"""

    file_name: str
    file_hash: str                                  # 整个备份文件的 SHA-256, 识别重复导入
    started_at: datetime
    status: str                                     # "success" | "partial" | "failed"
    total_count: int
    success_count: int
    failed_count: int

    source_type: str = "chatbox"
    format_key: str = "chatbox.v2"                  # 程序内部格式识别码, 与导入适配器对应
    id: int | None = None
    error_summary: str | None = None
    finished_at: datetime | None = None
    
    
    

