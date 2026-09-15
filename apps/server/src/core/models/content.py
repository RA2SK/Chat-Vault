"""内容域模型, 描述一次导入产生的完整内容图

图内的对应关系是:
Conversation 与 Branch 1:N, Branch 与 Message 1:N,
Attachment 与 Message N:1

Content 域不使用应用侧 id, 图内所有实体一律以 source_id 互相引用.
这些 source_id 已经过命名空间处理, 在全库范围内唯一, 是模型的唯一身份来源.
Branch.source_id 由 Conversation.source_id 派生, Attachment 通过 message_source_id
归属于 Message
"""

from dataclasses import dataclass, field
from datetime import datetime

from core.enums import AttachmentType, MessageRole, SourceType
from core.types import Checksum, ImportBatchId, UserId


@dataclass
class Conversation:
    """对话模型, 代表一次完整的对话, 包括主链和消息级分支"""

    source_id: str                                  # 幂等键, thread 的对应值为 {source_id}::thread::{thread_id}
    title: str

    source_archive: str | None = None               # 原始备份文件在存档目录当中的文件名, 由 import_service 填写
    source_entry: str | None = None                 # 会话在原始备份文件内的相对路径, 由适配器填写
    source_type: SourceType = SourceType.CHATBOX
    created_at: datetime | None = None              # 非权威数据, 由适配器根据 Branch 计算, 权威数据来自 message.timestamp
    updated_at: datetime | None = None              # 非权威数据, 由适配器根据 Branch 计算, 权威数据来自 message.timestamp
    is_published: bool = False
    import_batch_id: ImportBatchId | None = None    # -> ImportBatch.id

    branches: list["Branch"] = field(default_factory=list)      # 只和 Branch 对接


@dataclass
class Message:
    """消息模型, 表示一条链中的一条消息"""

    source_id: str                                  # 幂等键
    role: MessageRole                               # "user" | "assistant" | "system"
    content: str                                    # 正文内容
    position: int                                   # 在所属 Branch 中的序号, 不等同于输入的原始数据中的同名字段

    thinking: str = ""                              # 思考内容, 导入时清洗, 默认不展示
    model: str | None = None                        # 生成该消息的模型名
    timestamp: datetime | None = None

    edited_at: datetime | None = None               # 最后编辑时间
    edited_by: UserId | None = None

    attachments: list["Attachment"] = field(default_factory=list)


@dataclass
class Branch:
    """消息链模型, 包含主链和 messageForksHash 产生的历史分支"""

    source_id: str                                  # 幂等键; 主链的对应值为 {session_id}::main
    index: int
    fork_message_source_id: str | None = None       # 主链为 None，其他链指向锚点消息

    created_at: datetime | None = None              # 非权威数据, 由适配器根据时间戳最小的消息计算, 权威数据来自 message.timestamp
    updated_at: datetime | None = None              # 非权威数据, 由适配器根据时间戳最大的消息计算, 权威数据来自 message.timestamp
    is_current: bool = False                        # 当前链; 导入的主链设为 True

    messages: list[Message] = field(default_factory=list)


@dataclass
class Attachment:
    """附件模型, 表示一条消息下的一个附件"""

    message_source_id: str                          # 附件所属 Message 的 source_id, 入库后成为指向 messages.source_id 的外键
    attach_type: AttachmentType                     # "image" | "file" | "other"
    source_ref: str                                 # 资源引用标识, 禁止绝对路径

    display_name: str | None = None
    mime_type: str | None = None
    checksum: Checksum | None = None                # 资源去重
    size: int | None = None                         # 资源大小, 单位为字节
