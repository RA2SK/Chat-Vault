"""根据查询条件读取对话内容, 组织分支, 消息和附件关系, 并生成查询调用方可使用的结果

`ConversationDetail` 的定义已经移到 `modules.interfaces.querying_intf`, 因为它描述的是
一次查询调用的产出形状, 属于调用契约. 这里保留同名导入, 使调用方仍然可以
从本模块取到它, 不必关心契约层的组织方式.
"""

from dataclasses import dataclass

from core.models import (
    Attachment,
    Branch,
    Conversation,
    Message,
)
from modules.interfaces.querying_intf import ConversationDetail
from modules.repositories import (
    AttachmentRepository,
    BranchRepository,
    ConversationRepository,
    MessageRepository,
)

__all__ = ["ConversationDetail", "QueryService"]


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

            for message in branch_messages:
                message_attachments = self.list_attachments(message.source_id)
                attachments[message.source_id] = message_attachments
                message.attachments = message_attachments

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


    def get_message(self, message_source_id: str) -> Message | None:
        """根据来源 ID 获取一条消息

        供评论等服务判断消息是否存在, 避免它们直接访问消息仓储.
        """

        return self.message_repository.get_by_source_id(message_source_id)


    def get_message_conversation_source_id(self, message_source_id: str) -> str | None:
        """获取某条消息所属对话的来源 ID, 消息不存在时返回 None"""

        return self.message_repository.get_conversation_source_id(message_source_id)
