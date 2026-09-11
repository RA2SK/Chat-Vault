"""
整个程序使用的核心模型, 但不涉及具体实现
内容域内具体的对应关系是: 
Conversation 与 Branch 1:N, Branch 与 Message 1:N, 
Branch 与 Attachment 1:N, Attachment 与 Message N:1,
AdminMark 和 Comment 与 Message 或 Conversation 的关系待定
"""

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

    source_id: str                                  # 幂等键, thread 的对应值为 {source_id}::thread::{thread_id}
    title: str

    source_archive: str | None = None               # 原始备份文件在存档目录当中的文件名, 由 import_service 填写
    source_entry: str | None = None                 # 会话在原始备份文件内的相对路径, 由适配器填写
    source_type: str = "chatbox"                    # "chatbox" | "cherry studio" | "other"
    id: int | None = None                           
    created_at: datetime | None = None              # 非权威数据, 由适配器根据 Branch 计算, 权威数据来自 message.timestamp
    updated_at: datetime | None = None              # 非权威数据, 由适配器根据 Branch 计算, 权威数据来自 message.timestamp
    is_published: bool = False
    import_batch: int | None = None                 # -> ImportBatch.id
    
    branches: list["Branch"] = field(default_factory=list)      # 只和 Branch 对接


@dataclass
class Message:
    """消息模型, 表示一条链中的一条消息"""

    # === 输入层 ===
    source_id: str                                  # 幂等键
    role: str                                       # "user" | "assistant" | "system"
    content: str                                    # 正文内容
    position: int                                   # 在所属 Branch 中的序号, 不等同于输入的原始数据中的同名字段

    thinking: str = ""                              # 思考内容, 导入时清洗, 默认不展示
    model: str | None = None                        # 生成该消息的模型名
    timestamp: datetime | None = None               

    # === 业务层 ===
    id: int | None = None
    branch_id: int | None = None                    # 由所属 Branch 回填, 禁止依赖 Conversation
    edited_at: datetime | None = None               # 最后编辑时间
    edited_by: int | None = None


@dataclass
class Branch:
    """消息链模型, 包含主链和 messageForksHash 产生的历史分支"""

    source_id: str                                  # 幂等键; 主链的对应值为 {session_id}::main
    index: int
    fork_message_source_id: str | None = None       # 主链为 None，其他链指向锚点消息

    created_at: datetime | None = None              # 非权威数据, 由适配器根据时间戳最小的消息计算, 权威数据来自 message.timestamp
    updated_at: datetime | None = None              # 非权威数据, 由适配器根据时间戳最大的消息计算, 权威数据来自 message.timestamp
    is_current: bool = False                        # 当前链; 导入的主链设为 True
    id: int | None = None
    conversation_id: int | None = None              

    messages: list[Message] = field(default_factory=list)
    attachments: list["Attachment"] = field(default_factory=list)


@dataclass
class Attachment:
    """附件模型, 表示一条链中的一个附件"""

    message_source_id: str                          # 过渡用, 输入阶段标定附件出现在哪条消息, 入库后被 message_id 取代
    attach_type: str                                # "image" | "file" | "other"
    source_ref: str                                 # 资源引用标识, 禁止绝对路径

    display_name: str | None = None                 
    mime_type: str | None = None                    
    checksum: Checksum | None = None                # 资源去重
    size: int | None = None                         # 资源大小, 单位为字节

    id: int | None = None
    branch_id: int | None = None                    # 由所属 Branch 回填
    message_id: int | None = None                   # 由 message_source_id 解析后回填
   

@dataclass
class Comment:
    """评论模型, 表示用户对消息或对话的评论"""

    conversation_id: int
    message_id: int
    target_type: str                                # "conversation" | "message"

    content: str
    created_at: datetime
    created_by: int | None = None
    nickname: str = "anonymous"

    is_deleted: bool = False                        # 管理员软删除


@dataclass
class AdminMark:
    """管理员标记模型, 用于代表管理员用户对消息进行的标记"""

    message_id: int
    mark_type: str                                  # "highlight" | "pin" | "other"
    created_at: datetime
    created_by: int                                 # -> User.id

    is_deleted: bool = False                        # 管理员软删除
    id: int | None = None


@dataclass
class MessageRevision:
    """消息历史模型, 用于记录消息的编辑记录和迭代版本"""

    message_id: int
    revision_no: int                                # 迭代版本
    content: str                                    # 本迭代的正文内容
    thinking: str                                   # 本迭代的思考内容
    created_at: datetime
    created_by: int
    reason: str | None = None                       # 管理员的修改备注
    id: int | None = None


# ============ 管理域 ============

@dataclass
class User:
    """用户信息模型, 包括普通用户和管理员"""

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
    
    
    

