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
    "ConversationDetail",
    "ImportBatch",
    "ImportService",
    "Message",
    "MessageRevision",
    "PermissionService",
    "QueryService",
    "ServiceContainer",
    "User",
]


def __getattr__(name: str) -> object:
    if name == "ImportService":
        from modules.services.import_service import ImportService

        return ImportService
    if name == "PermissionService":
        from modules.services.permission_service import PermissionService

        return PermissionService
    if name in {"ConversationDetail", "QueryService"}:
        from modules.services.query_service import ConversationDetail, QueryService

        return {"ConversationDetail": ConversationDetail, "QueryService": QueryService}[name]
    if name == "ServiceContainer":
        from core.services import ServiceContainer

        return ServiceContainer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
