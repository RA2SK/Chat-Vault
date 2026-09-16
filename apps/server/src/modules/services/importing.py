"""收适配器生成的导入内容, 执行完整性检查, 重复导入判断, 批次管理和仓储写入流程"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterator

from core.enums import AttachmentType, ImportStatus, MessageRole, SourceType
from core.exceptions import ImportFailedError, ValidationError
from core.messages import MessageKey, render
from core.models import (
    Attachment,
    Branch,
    Conversation,
    ImportBatch,
    Message,
)
from modules.adapters.base import BaseImporter
from modules.interfaces.importing_intf import ParseResult
from modules.repositories import (
    AttachmentRepository,
    BranchRepository,
    ConversationRepository,
    ImportBatchRepository,
    MessageRepository,
)
from modules.repositories.database import transaction


def _hash_file(path: Path) -> str:
    """计算文件内容摘要, 作为重复导入判断的依据"""

    return sha256(path.read_bytes()).hexdigest()


def _to_source_type(raw: object) -> SourceType:
    """把适配器声明的来源名称收敛为 SourceType, 无法识别时归入 other"""

    if isinstance(raw, SourceType):
        return raw

    try:
        return SourceType(str(raw))
    except ValueError:
        return SourceType.OTHER


@dataclass
class ImportService:
    """备份文件导入服务, 负责导入流程编排"""

    # 服务层自行持有连接, 以便把一次导入划成一个事务
    connection: sqlite3.Connection

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
            raise ImportFailedError(MessageKey.IMPORT_FILE_NOT_FOUND, path=path)

        if not path.is_file():
            raise ImportFailedError(MessageKey.IMPORT_PATH_NOT_FILE, path=path)

        if not importer.detect(path):
            raise ImportFailedError(
                MessageKey.IMPORT_FORMAT_MISMATCH,
                path=path,
                format_key=importer.format_key,
            )

        results = importer.parse(path)
        source_type = _to_source_type(getattr(importer, "source_type", None))

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
        source_type: SourceType = SourceType.OTHER,
    ) -> ImportBatch:
        """处理输入适配器产生的解析结果"""

        path = Path(path)

        # === 重复导入检测 ===
        # 同一份文件内容已经成功导入过时, 直接返回原批次, 不重复写入库
        # 摘要只算一次, 批次记录直接复用, 避免对同一个文件读两遍
        file_hash = _hash_file(path)
        duplicate = self.find_duplicate_import(file_hash)
        if duplicate is not None:
            return duplicate

        # === 创建批次记录 ===
        import_batch = self._create_import_batch(
            path=path,
            file_hash=file_hash,
            format_key=format_key,
            source_type=source_type,
        )

        try:
            # === 逐条消费解析器返回的 ParseResult ===
            for result in results:
                self._handle_parse_result(result, import_batch)

        except Exception as exc:
            # 批次记录本身也要落库, 否则失败原因只存在于内存里, 调用方无从查证.
            # 这里刻意不把异常文本写进 error_summary: 异常文本是给开发者看的,
            # 可能带路径和内部细节, 而 error_summary 是面向调用方的字段.
            import_batch.status = ImportStatus.FAILED
            import_batch.error_summary = render(
                MessageKey.IMPORT_CONVERSATION_SAVE_FAILED,
                reason=type(exc).__name__,
            )
            import_batch.finished_at = datetime.now(timezone.utc)

            with transaction(self.connection):
                self.import_batch_repository.update(import_batch)
            raise

        # === 更新批次的完成时间和状态 ===
        self._finalize_import_batch(import_batch)

        with transaction(self.connection):
            self.import_batch_repository.update(import_batch)

        return import_batch


    def find_duplicate_import(self, file_hash: str) -> ImportBatch | None:
        """按文件内容摘要查找已成功导入的批次

        返回最近一次同内容且不是失败状态的批次, 供调用方在导入前
        预先判断; `import_results` 内部也用它避免重复写入.
        """

        if not file_hash:
            return None

        import_batch = self.import_batch_repository.get_by_file_hash(file_hash)

        if import_batch is None or import_batch.status == ImportStatus.FAILED:
            return None

        return import_batch


    def _create_import_batch(
        self,
        path: Path,
        file_hash: str,
        format_key: str,
        source_type: SourceType,
    ) -> ImportBatch:
        """创建处于初始状态的导入批次"""

        import_time = datetime.now(timezone.utc)

        import_batch = ImportBatch(
            file_name=path.name,
            file_hash=file_hash,
            started_at=import_time,
            status=ImportStatus.SUCCESS,
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
                render(MessageKey.IMPORT_RESULT_EMPTY),
                source_id=result.source_id,
                source_ref=result.source_ref,
            )
            return

        try:
            self._save_conversation(result.conversation, import_batch)

        except Exception as exc:
            self._record_error(
                import_batch,
                render(
                    MessageKey.IMPORT_CONVERSATION_SAVE_FAILED,
                    reason=type(exc).__name__,
                ),
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

        conversation.import_batch_id = import_batch.id
        conversation.source_archive = import_batch.file_name
        existing = self._find_existing_conversation(conversation)

        with transaction(self.connection):
            if existing is None:
                self.conversation_repository.create(conversation)
            else:
                # 发布状态属于管理域, 重复导入不能因为导入模型的默认值而取消发布
                conversation.is_published = existing.is_published
                self.conversation_repository.update(conversation)

            for branch in conversation.branches:                # 逐个处理分支链
                self._save_branch(branch, conversation)


    def _save_branch(
        self,
        branch: Branch,
        conversation: Conversation,
    ) -> None:
        """保存或复用一个对话分支, 并保存其消息和附件"""

        existing = self.branch_repository.get_by_source_id(branch.source_id)

        if existing is None:
            self.branch_repository.create(branch, conversation.source_id)
        else:
            branch.is_current = existing.is_current             # 当前链标记属管理域, 重复导入不覆盖
            self.branch_repository.update(branch)

        for message in branch.messages:                         # 逐个处理消息
            self._save_message(message, branch)


    def _save_message(
        self,
        message: Message,
        branch: Branch,
    ) -> None:
        """保存或更新一条消息, 并保存其附件

        重复导入不能抹掉管理员对消息做的编辑: 已编辑过的消息保留原有内容和
        编辑记录, 未编辑过的消息才允许按新解析结果覆盖.
        """

        existing = self.message_repository.get_by_source_id(message.source_id)

        if existing is None:
            self.message_repository.create(message, branch.source_id)
        else:
            message.edited_at = existing.edited_at
            message.edited_by = existing.edited_by

            if existing.edited_at is None:
                self.message_repository.update(message)

        self._save_attachments(message)


    def _save_attachments(self, message: Message) -> None:
        """保存或更新一条消息下的全部附件

        附件的主键是 (message_source_id, source_ref), 因此判断"是否已存在"
        只需要按 source_ref 查一次. 这里把该消息的附件一次性取成字典, 避免
        每条附件都重新查一遍库.
        """

        existing_by_ref = {
            item.source_ref: item
            for item in self.attachment_repository.list_by_message(message.source_id)
        }

        for attachment in message.attachments:                  # 逐个处理附件
            self._save_one_attachment(attachment, existing_by_ref)


    def _save_one_attachment(
        self,
        attachment: Attachment,
        existing_by_ref: dict[str, Attachment],
    ) -> None:
        """保存或更新一个附件, 复用调用方已经查好的同消息附件字典

        ``existing_by_ref`` 由 :meth:`_save_attachments` 构造并传入, 本方法
        不再自己查库, 否则同一条消息的 N 个附件会产生 N 次完全相同的查询.
        """

        if attachment.source_ref not in existing_by_ref:
            self.attachment_repository.create(attachment)
        else:
            self.attachment_repository.update(attachment)


    def _validate_conversation(self, conversation: Conversation) -> None:
        """校验对话、分支、消息和附件之间的业务关系"""

        if not conversation.source_id.strip():
            raise ValidationError(MessageKey.CONVERSATION_SOURCE_ID_EMPTY)
        if not conversation.title.strip():
            raise ValidationError(MessageKey.CONVERSATION_TITLE_EMPTY)
        if not conversation.source_type.strip():
            raise ValidationError(MessageKey.CONVERSATION_SOURCE_TYPE_EMPTY)

        branch_source_ids: set[str] = set()
        for branch in conversation.branches:
            if not branch.source_id.strip():
                raise ValidationError(MessageKey.BRANCH_SOURCE_ID_EMPTY)
            if branch.source_id in branch_source_ids:
                raise ValidationError(
                    MessageKey.BRANCH_SOURCE_ID_DUPLICATED,
                    branch_source_id=branch.source_id,
                )
            branch_source_ids.add(branch.source_id)

            if branch.index < 0:
                raise ValidationError(MessageKey.BRANCH_INDEX_NEGATIVE)

            message_source_ids: set[str] = set()
            message_positions: set[int] = set()
            for message in branch.messages:
                if not message.source_id.strip():
                    raise ValidationError(MessageKey.MESSAGE_SOURCE_ID_EMPTY)
                if message.source_id in message_source_ids:
                    raise ValidationError(
                        MessageKey.MESSAGE_SOURCE_ID_DUPLICATED,
                        message_source_id=message.source_id,
                    )
                message_source_ids.add(message.source_id)

                if message.position < 0:
                    raise ValidationError(MessageKey.MESSAGE_POSITION_NEGATIVE)
                if message.position in message_positions:
                    raise ValidationError(
                        MessageKey.MESSAGE_POSITION_DUPLICATED,
                        position=message.position,
                    )
                message_positions.add(message.position)

                if message.role not in set(MessageRole):
                    raise ValidationError(
                        MessageKey.MESSAGE_ROLE_UNSUPPORTED,
                        role=message.role,
                    )

                for attachment in message.attachments:
                    if not attachment.message_source_id.strip():
                        raise ValidationError(
                            MessageKey.ATTACHMENT_MESSAGE_SOURCE_ID_EMPTY
                        )
                    if attachment.message_source_id != message.source_id:
                        raise ValidationError(
                            MessageKey.ATTACHMENT_MESSAGE_MISMATCH,
                            message_source_id=attachment.message_source_id,
                        )
                    if not attachment.source_ref.strip():
                        raise ValidationError(
                            MessageKey.ATTACHMENT_SOURCE_REF_EMPTY
                        )
                    if attachment.attach_type not in set(AttachmentType):
                        raise ValidationError(
                            MessageKey.ATTACHMENT_TYPE_UNSUPPORTED,
                            attach_type=attachment.attach_type,
                        )
                    if attachment.size is not None and attachment.size < 0:
                        raise ValidationError(MessageKey.ATTACHMENT_SIZE_NEGATIVE)


    def _find_existing_conversation(
        self,
        conversation: Conversation,
    ) -> Conversation | None:
        """根据来源 ID 查找已有对话, 用于实现重复导入幂等去重"""

        if not conversation.source_id.strip():
            raise ValidationError(MessageKey.CONVERSATION_SOURCE_ID_REQUIRED)

        return self.conversation_repository.get_by_source_id(
            conversation.source_id
        )


    def _finalize_import_batch(self, import_batch: ImportBatch) -> None:
        """根据导入统计结果更新批次最终状态

        单条解析失败只体现在 `failed_count` 和 `error_summary` 上, 不改变批次
        状态: 批次状态回答的是"这次导入有没有整体成立", 而不是"有没有瑕疵".
        """

        import_batch.finished_at = datetime.now(timezone.utc)

        if import_batch.success_count == 0 and import_batch.failed_count > 0:
            import_batch.status = ImportStatus.FAILED
        else:
            import_batch.status = ImportStatus.SUCCESS


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
