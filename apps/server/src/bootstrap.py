"""集中创建数据库连接, 适配器, 仓储和业务服务, 并完成具体实现之间的依赖组装"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from modules.interfaces.comments_intf import CommentServiceContract
from modules.interfaces.importing_intf import ImportServiceContract
from modules.interfaces.moderation_intf import ModerationServiceContract
from modules.interfaces.publishing_intf import PublicationServiceContract
from modules.interfaces.querying_intf import QueryingServiceContract
from modules.interfaces.users_intf import UserServiceContract
from modules.repositories import (
    AdminMarkRepository,
    AttachmentRepository,
    BranchRepository,
    CommentRepository,
    ConversationRepository,
    ImportBatchRepository,
    MessageRepository,
    UserRepository,
)
from modules.repositories.database import get_connection, initialize_database
from modules.services.comments import CommentService
from modules.services.importing import ImportService
from modules.services.moderation import ModerationService
from modules.services.publishing import PublishingService
from modules.services.querying import QueryService
from modules.services.users import UserService


@dataclass
class ServiceContainer:
    """应用运行期间使用的数据库和核心服务集合

    字段按接口契约层声明的类型标注, 调用方只依赖契约, 不依赖具体实现.
    装配仍然使用具体实现, 具体实现不继承契约, 依靠结构匹配满足契约.
    """

    connection: sqlite3.Connection
    import_service: ImportServiceContract
    query_service: QueryingServiceContract
    user_service: UserServiceContract
    publishing_service: PublicationServiceContract
    moderation_service: ModerationServiceContract
    comment_service: CommentServiceContract

    @classmethod
    def create(
        cls,
        database_path: Path | None = None,
        initialize: bool = True,
    ) -> "ServiceContainer":
        """创建并组装核心服务"""

        if database_path is None:
            connection = get_connection()
        else:
            connection = get_connection(database_path)

        if initialize:
            initialize_database(connection)

        import_batch_repository = ImportBatchRepository(connection)
        conversation_repository = ConversationRepository(connection)
        branch_repository = BranchRepository(connection)
        message_repository = MessageRepository(connection)
        attachment_repository = AttachmentRepository(connection)
        user_repository = UserRepository(connection)
        comment_repository = CommentRepository(connection)
        admin_mark_repository = AdminMarkRepository(connection)

        import_service = ImportService(
            import_batch_repository=import_batch_repository,
            conversation_repository=conversation_repository,
            branch_repository=branch_repository,
            message_repository=message_repository,
            attachment_repository=attachment_repository,
        )
        query_service = QueryService(
            conversation_repository=conversation_repository,
            branch_repository=branch_repository,
            message_repository=message_repository,
            attachment_repository=attachment_repository,
        )
        user_service = UserService(user_repository=user_repository)
        publishing_service = PublishingService(
            query_service=query_service,
            conversation_repository=conversation_repository,
        )
        moderation_service = ModerationService(
            admin_mark_repository=admin_mark_repository,
            message_repository=message_repository,
        )
        comment_service = CommentService(
            comment_repository=comment_repository,
            query_service=query_service,
        )

        return cls(
            connection=connection,
            import_service=import_service,
            query_service=query_service,
            user_service=user_service,
            publishing_service=publishing_service,
            moderation_service=moderation_service,
            comment_service=comment_service,
        )


    def close(self) -> None:
        """关闭服务使用的数据库连接"""

        self.connection.close()
