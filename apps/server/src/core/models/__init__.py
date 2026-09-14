"""整个程序使用的核心模型, 但不涉及具体实现

内容域内具体的对应关系是: 
Conversation 与 Branch 1:N, Branch 与 Message 1:N, 
Attachment 与 Message N:1,
AdminMark 和 Comment 与 Message 或 Conversation 的关系待定

模型按业务域分文件:
- content: 导入产生的内容图
- interaction: 用户在内容之上产生的操作记录
- identity: 访问系统的用户主体
- operations: 导入过程自身的记录

内容域以 source_id 作为身份, 互动域与身份域, 运维域使用应用侧生成的 id

本模块只做统一导出, 调用方继续使用 ``core.models`` 这一稳定路径
"""

from core.models.content import Attachment, Branch, Conversation, Message
from core.models.identity import User
from core.models.interaction import AdminMark, Comment, MessageRevision
from core.models.operations import ImportBatch
from core.types import Checksum

__all__ = [
    "AdminMark",
    "Attachment",
    "Branch",
    "Checksum",
    "Comment",
    "Conversation",
    "ImportBatch",
    "Message",
    "MessageRevision",
    "User",
]