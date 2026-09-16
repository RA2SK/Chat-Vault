"""接口契约层的公共导出

接口契约层按业务能力组织, 每个文件对应一组稳定的输入, 输出和调用契约.
本文件统一导出所有契约, 调用方既可以从此处导入, 也可以从具体契约文件导入.

本层只依赖 `core` 和本层内部的其他契约文件, 不依赖任何具体实现.
具体实现反过来依赖本层, 因此这里的导入是安全的, 不会形成循环依赖.

调用约定: 具体实现不继承这些协议, 而是依靠结构匹配被动满足.
`@runtime_checkable` 的协议可以用 `isinstance()` 做运行时冒烟检查, 但
`isinstance()` 只比较方法名, 不比较签名. 签名是否一致只能靠静态类型检查器
验证, 因此本层的价值依赖类型检查器, 不能只依赖运行时断言.
"""

from modules.interfaces.comments_intf import (
    CommentServiceContract,
    CommentSubmission,
)
from modules.interfaces.exporting_intf import (
    ContentExporter,
    ExportingService,
)
from modules.interfaces.importing_intf import (
    Importer,
    ImportServiceContract,
    ParseResult,
)
from modules.interfaces.moderation_intf import (
    MessageEditRequest,
    ModerationServiceContract,
)
from modules.interfaces.publishing_intf import (
    PublicationServiceContract,
    PublishedConversationSummary,
    PublishedConversationView,
    PublishedMessageView,
)
from modules.interfaces.querying_intf import (
    ConversationDetail,
    QueryingServiceContract,
)
from modules.interfaces.repositories_intf import (
    AdminMarkStore,
    AttachmentStore,
    BranchStore,
    CommentStore,
    ConversationStore,
    ImportBatchStore,
    MessageStore,
    UserStore,
)
from modules.interfaces.users_intf import (
    IdGenerator,
    PasswordChange,
    SessionStore,
    UserRegistration,
    UserServiceContract,
    UserView,
)

__all__ = [
    "AdminMarkStore",
    "AttachmentStore",
    "BranchStore",
    "CommentServiceContract",
    "CommentStore",
    "CommentSubmission",
    "ContentExporter",
    "ConversationDetail",
    "ConversationStore",
    "ExportingService",
    "IdGenerator",
    "ImportBatchStore",
    "Importer",
    "ImportServiceContract",
    "MessageEditRequest",
    "MessageStore",
    "ModerationServiceContract",
    "ParseResult",
    "PasswordChange",
    "PublicationServiceContract",
    "PublishedConversationSummary",
    "PublishedConversationView",
    "PublishedMessageView",
    "QueryingServiceContract",
    "SessionStore",
    "UserRegistration",
    "UserServiceContract",
    "UserStore",
    "UserView",
]