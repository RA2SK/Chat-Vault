"""查询服务, 向 CLI、Markdown 导出器和未来的 Web 输出端提供统一的读取入口"""

from dataclasses import dataclass

from core.models import (
    Attachment,
    Branch,
    Conversation,
    Message,
)
from modules.repositories import (
    AttachmentRepository,
    BranchRepository,
    ConversationRepository,
    MessageRepository,
)


@dataclass
class ConversationDetail:
    """一个完整的对话详情及其关联内容

    两张映射表都以内容域的 source_id 为键:
    messages 以 Branch.source_id 为键, attachments 以 Message.source_id 为键
    """

    conversation: Conversation
    branches: list[Branch]
    messages: dict[str, list[Message]]
    attachments: dict[str, list[Attachment]]


@dataclass
class QueryService:
    """为输出端提供对话查询能力"""

    conversation_repository: ConversationRepository
    branch_repository: BranchRepository
    message_repository: MessageRepository
    attachment_repository: AttachmentRepository

    def list_conversations(self) -> list[Conversation]:
        """返回所有对话，供管理员或本地输出端使用"""

        return self.conversation_repository.list_all()


    def list_published_conversations(self) -> list[Conversation]:
        """返回已发布的对话，供普通用户或公开输出端使用"""

        return self.conversation_repository.list_published()


    def get_conversation(self, conversation_source_id: str) -> Conversation | None:
        """根据来源 ID 获取一个对话的基本信息"""

        return self.conversation_repository.get_by_source_id(conversation_source_id)


    def get_conversation_detail(
        self,
        conversation_source_id: str,
    ) -> ConversationDetail | None:
        """获取对话、分支、消息和附件组成的完整详情"""

        conversation = self.get_conversation(conversation_source_id)
        if conversation is None:
            return None

        branches = self.list_branches(conversation_source_id)
        messages: dict[str, list[Message]] = {}
        attachments: dict[str, list[Attachment]] = {}

        for branch in branches:
            branch_messages = self.list_messages(branch.source_id)
            messages[branch.source_id] = branch_messages
            branch.messages = branch_messages

            branch_attachments: list[Attachment] = []
            for message in branch_messages:
                message_attachments = self.list_attachments(message.source_id)
                attachments[message.source_id] = message_attachments
                branch_attachments.extend(message_attachments)

            branch.attachments = branch_attachments

        conversation.branches = branches
        return ConversationDetail(
            conversation=conversation,
            branches=branches,
            messages=messages,
            attachments=attachments,
        )


    def list_branches(self, conversation_source_id: str) -> list[Branch]:
        """获取某个对话下的分支列表"""

        return self.branch_repository.list_by_conversation(conversation_source_id)


    def list_messages(self, branch_source_id: str) -> list[Message]:
        """获取某个分支下按 position 排序的消息"""

        return self.message_repository.list_by_branch(branch_source_id)


    def list_attachments(self, message_source_id: str) -> list[Attachment]:
        """获取某条消息下的附件列表"""

        return self.attachment_repository.list_by_message(message_source_id)
