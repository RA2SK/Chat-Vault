"""面向核心模型的数据仓储接口

按业务域分文件实现, 本模块只做统一导出, 调用方继续使用
``modules.repositories`` 这一稳定路径
"""

from modules.repositories.comments import CommentRepository
from modules.repositories.conversations import BranchRepository, ConversationRepository
from modules.repositories.imports import ImportBatchRepository
from modules.repositories.messages import AttachmentRepository, MessageRepository
from modules.repositories.moderation import AdminMarkRepository
from modules.repositories.users import UserRepository

__all__ = [
    "AdminMarkRepository",
    "AttachmentRepository",
    "BranchRepository",
    "CommentRepository",
    "ConversationRepository",
    "ImportBatchRepository",
    "MessageRepository",
    "UserRepository",
]
