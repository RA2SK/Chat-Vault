"""导入服务, 负责协调输入适配器、业务模型和仓储层"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterator

from core.models import (
    Attachment,
    Branch,
    Conversation,
    ImportBatch,
    Message,
)
from modules.adapters.base import BaseImporter, ParseResult
from modules.repositories.repositories import (
    AttachmentRepository,
    BranchRepository,
    ConversationRepository,
    ImportBatchRepository,
    MessageRepository,
)


@dataclass
class ImportService:
    """备份文件导入服务, 负责导入流程编排"""

    # === 仓储层的各个接口 ===
    import_batch_repository: ImportBatchRepository
    conversation_repository: ConversationRepository
    branch_repository: BranchRepository
    message_repository: MessageRepository
    attachment_repository: AttachmentRepository

    def import_file(
        self,
        path: Path,
        importer: BaseImporter,
    ) -> ImportBatch:
        """导入一个备份文件, 并返回导入批次结果"""

        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"导入文件不存在: {path}")

        if not path.is_file():
            raise ValueError(f"导入路径不是文件: {path}")

        if not importer.detect(path):
            raise ValueError(
                f"输入文件格式与适配器不匹配: {path} "
                f"(format_key={importer.format_key})"
            )

        results = importer.parse(path)
        source_type=getattr(importer, "source_type", "unknown")

        return self.import_results(
            path=path,
            results=results,
            format_key=importer.format_key,
            source_type=source_type,
        )


    def import_results(
        self,
        path: Path,
        results: Iterator[ParseResult],
        format_key: str = "unknown",
        source_type: str = "unknown",
    ) -> ImportBatch:
        """处理输入适配器产生的解析结果"""

        # === 创建批次记录 ===
        path = Path(path)
        import_batch = self._create_import_batch(
            path=path,
            format_key=format_key,
            source_type=source_type,
        )

        try:
            # === 逐条消费解析器返回的 ParseResult ===
            for result in results:
                self._handle_parse_result(result, import_batch)

        except Exception as exc:

            import_batch.status = "failed"
            import_batch.error_summary = str(exc)
            import_batch.finished_at = datetime.now(timezone.utc)
            self.import_batch_repository.update(import_batch)
            raise

        # === 更新批次的完成时间和状态 ===
        self._finalize_import_batch(import_batch)
        self.import_batch_repository.update(import_batch)
        return import_batch


    def _create_import_batch(
        self,
        path: Path,
        format_key: str,
        source_type: str,
    ) -> ImportBatch:
        """创建处于初始状态的导入批次"""

        file_hash = sha256(path.read_bytes()).hexdigest()
        import_time = datetime.now(timezone.utc)

        import_batch = ImportBatch(
            file_name=path.name,
            file_hash=file_hash,
            started_at=import_time,
            status="success",
            total_count=0,
            success_count=0,
            failed_count=0,
            source_type=source_type,
            format_key=format_key,
        )

        self.import_batch_repository.create(import_batch)
        return import_batch


    def _handle_parse_result(
        self,
        result: ParseResult,
        import_batch: ImportBatch,
    ) -> None:
        """处理单个解析结果, 并更新导入统计"""

        import_batch.total_count += 1

        for warning in result.warnings:                 # warnings 不为空 -> 记录适配器发现的非致命问题
            self._record_warning(import_batch, warning)

        if result.error is not None:                    # error 不为空 -> 当前会话解析失败, 记录错误
            self._record_error(
                import_batch,
                result.error,
                source_id=result.source_id,
                source_ref=result.source_ref,
            )
            return                                      # conversation 不为空 -> 校验并保存一个对话

        if result.conversation is None:                 
            self._record_error(
                import_batch,
                "解析结果既没有 conversation, 也没有 error",
                source_id=result.source_id,
                source_ref=result.source_ref,
            )
            return

        try:
            self._save_conversation(result.conversation, import_batch)

        except Exception as exc:
            self._record_error(
                import_batch,
                f"保存会话失败: {exc}",
                source_id=result.source_id,
                source_ref=result.source_ref,
            )
            return

        import_batch.success_count += 1


    def _save_conversation(
        self,
        conversation: Conversation,
        import_batch: ImportBatch,
    ) -> None:
        """保存或更新一个对话及其关联数据"""

        self._validate_conversation(conversation)

        if import_batch.id is None:
            raise ValueError("保存对话前必须存在 import_batch.id")

        conversation.import_batch = import_batch.id
        existing = self._find_existing_conversation(conversation)

        if existing is None:
            self.conversation_repository.create(conversation)
        else:
            conversation.id = existing.id
            conversation.is_published = existing.is_published       # 发布状态属于管理域，重复导入不能因为导入模型的默认值而取消发布
            self.conversation_repository.update(conversation)

        if conversation.id is None:
            raise RuntimeError("保存对话后未获得 conversation.id")

        for branch in conversation.branches:                        # 逐个处理分支链
            self._save_branch(branch, conversation)


    def _save_branch(
        self,
        branch: Branch,
        conversation: Conversation,
    ) -> None:
        """保存或复用一个对话分支, 并保存其消息和附件"""

        if conversation.id is None:
            raise ValueError("保存链前必须存在 conversation.id")

        branch.conversation_id = conversation.id
        existing = self.branch_repository.get_by_source_id(branch.source_id)

        if existing is None:
            self.branch_repository.create(branch)
        else:
            branch.id = existing.id
            branch.conversation_id = conversation.id

        if branch.id is None:
            raise RuntimeError("保存链后未获得 branch.id")

        for message in branch.messages:                             # 逐个处理消息
            self._save_message(message, branch)

        for attachment in branch.attachments:                       # 逐个处理附件
            self._save_attachment(attachment, branch)


    def _save_message(
        self,
        message: Message,
        branch: Branch,
    ) -> None:
        """保存或更新一条消息"""

        if branch.id is None:
            raise ValueError("保存消息前必须存在 branch.id")

        message.branch_id = branch.id
        existing = self.message_repository.get_by_source_id(message.source_id)

        if existing is None:
            self.message_repository.create(message)
        else:
            message.id = existing.id
            self.message_repository.update(message)

        if message.id is None:
            raise RuntimeError("保存消息后未获得 message.id")


    def _save_attachment(
        self,
        attachment: Attachment,
        branch: Branch,
    ) -> None:
        """保存或更新一个附件, 并将其绑定到对应消息"""

        if branch.id is None:
            raise ValueError("保存附件前必须存在 branch.id")

        attachment.branch_id = branch.id
        message = next(
            (
                item
                for item in branch.messages
                if item.source_id == attachment.message_source_id
            ),
            None,
        )
        if message is None or message.id is None:
            raise ValueError(
                "附件引用的消息不存在: "
                f"{attachment.message_source_id}"
            )

        attachment.message_id = message.id
        existing = next(
            (
                item
                for item in self.attachment_repository.list_by_message(
                    message.id
                )
                if item.source_ref == attachment.source_ref
            ),
            None,
        )

        if existing is None:
            self.attachment_repository.create(attachment)
        else:
            attachment.id = existing.id
            self.attachment_repository.update(attachment)

        if attachment.id is None:
            raise RuntimeError("保存附件后未获得 attachment.id")


    def _validate_conversation(self, conversation: Conversation) -> None:
        """校验对话、分支、消息和附件之间的业务关系"""

        if not conversation.source_id.strip():
            raise ValueError("Conversation.source_id 不能为空")
        if not conversation.title.strip():
            raise ValueError("Conversation.title 不能为空")
        if not conversation.source_type.strip():
            raise ValueError("Conversation.source_type 不能为空")

        branch_source_ids: set[str] = set()
        for branch in conversation.branches:
            if not branch.source_id.strip():
                raise ValueError("Branch.source_id 不能为空")
            if branch.source_id in branch_source_ids:
                raise ValueError(
                    f"Conversation 中存在重复的 Branch.source_id: {branch.source_id}"
                )
            branch_source_ids.add(branch.source_id)

            if branch.index < 0:
                raise ValueError("Branch.index 不能小于 0")

            message_source_ids: set[str] = set()
            message_positions: set[int] = set()
            for message in branch.messages:
                if not message.source_id.strip():
                    raise ValueError("Message.source_id 不能为空")
                if message.source_id in message_source_ids:
                    raise ValueError(
                        f"Branch 中存在重复的 Message.source_id: {message.source_id}"
                    )
                message_source_ids.add(message.source_id)

                if message.position < 0:
                    raise ValueError("Message.position 不能小于 0")
                if message.position in message_positions:
                    raise ValueError(
                        f"Branch 中存在重复的 Message.position: {message.position}"
                    )
                message_positions.add(message.position)

                if message.role not in {"user", "assistant", "system"}:
                    raise ValueError(f"不支持的消息角色: {message.role}")

            for attachment in branch.attachments:
                if not attachment.message_source_id.strip():
                    raise ValueError("Attachment.message_source_id 不能为空")
                if attachment.message_source_id not in message_source_ids:
                    raise ValueError(
                        "附件引用了当前分支中不存在的消息: "
                        f"{attachment.message_source_id}"
                    )
                if not attachment.source_ref.strip():
                    raise ValueError("Attachment.source_ref 不能为空")
                if attachment.attach_type not in {"image", "file", "other"}:
                    raise ValueError(
                        f"不支持的附件类型: {attachment.attach_type}"
                    )
                if attachment.size is not None and attachment.size < 0:
                    raise ValueError("Attachment.size 不能小于 0")


    def _find_existing_conversation(
        self,
        conversation: Conversation,
    ) -> Conversation | None:
        """根据来源 ID 查找已有对话, 用于实现重复导入幂等去重"""

        if not conversation.source_id.strip():
            raise ValueError("查找已有对话前必须存在 source_id")

        return self.conversation_repository.get_by_source_id(
            conversation.source_id
        )


    def _finalize_import_batch(self, import_batch: ImportBatch) -> None:
        """根据导入统计结果更新批次最终状态"""

        import_batch.finished_at = datetime.now(timezone.utc)

        if import_batch.failed_count == 0:
            import_batch.status = "success"
        elif import_batch.success_count == 0:
            import_batch.status = "failed"
        else:
            import_batch.status = "partial"


    def _record_warning(
        self,
        import_batch: ImportBatch,
        warning: str,
    ) -> None:
        """记录单个解析警告"""

        if not warning:
            return

        if import_batch.error_summary:
            import_batch.error_summary += f"\n警告: {warning}"
        else:
            import_batch.error_summary = f"警告: {warning}"


    def _record_error(
        self,
        import_batch: ImportBatch,
        error: str,
        source_id: str | None = None,
        source_ref: str | None = None,
    ) -> None:
        """记录单个解析错误"""

        details = error

        if source_id:
            details = f"{details} [source_id={source_id}]"
        if source_ref:
            details = f"{details} [source_ref={source_ref}]"

        import_batch.failed_count += 1

        if import_batch.error_summary:
            import_batch.error_summary += f"\n{details}"
        else:
            import_batch.error_summary = details
