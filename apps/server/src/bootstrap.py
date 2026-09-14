"""核心业务服务的组合入口, 负责创建数据库连接、Repository 和核心服务对象等, 避免输出端重复编写组装代码"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from modules.repositories.database import get_connection, initialize_database
from modules.repositories.repositories import (
    AttachmentRepository,
    BranchRepository,
    ConversationRepository,
    ImportBatchRepository,
    MessageRepository,
)
from modules.services.importing import ImportService
from modules.services.querying import QueryService


@dataclass
class ServiceContainer:
    """应用运行期间使用的数据库和核心服务集合"""

    connection: sqlite3.Connection
    import_service: ImportService
    query_service: QueryService

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

        return cls(
            connection=connection,
            import_service=import_service,
            query_service=query_service,
        )


    def close(self) -> None:
        """关闭服务使用的数据库连接"""

        self.connection.close()
