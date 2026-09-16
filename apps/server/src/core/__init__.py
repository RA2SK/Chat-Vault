"""Chat Vault 核心业务层公共接口"""

from core.models import (
    AdminMark,
    Attachment,
    Branch,
    Comment,
    Conversation,
    ImportBatch,
    Message,
    MessageRevision,
    User,
)

__all__ = [
    "AdminMark",
    "Attachment",
    "Branch",
    "Comment",
    "Conversation",
    "ImportBatch",
    "Message",
    "MessageRevision",
    "User",
]

# 这个包只对外暴露领域模型.
# ConversationDetail 是查询调用的结果形状, 它组织的是模型而不是模型本身,
# 因此属于接口层, 由 modules.interfaces 导出.
# 服务实现和容器不是核心层概念, 需要时直接从各自的模块导入.
