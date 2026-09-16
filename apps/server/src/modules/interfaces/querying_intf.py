"""查询能力契约, 定义读取对话内容时对调用方承诺的结果形状和调用方式

`ConversationDetail` 定义在这里而不是查询服务中, 因为它描述的是"一次查询调用的
产出形状". 该结果由多个仓储的查询结果拼装而成, 只有服务层知道怎么拼, 但只有
调用方知道需要什么形状. 把它放进接口层, 可以让调用方只依赖契约, 不必让
契约反向依赖某个具体服务, 也避免仓储为了迎合调用方而返回拼装好的查询结果.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.models import (
    Attachment,
    Branch,
    Conversation,
    Message,
)
from core.pagination import Page, PageResult


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


@runtime_checkable
class QueryingServiceContract(Protocol):
    """查询能力契约

    具体实现的构造依赖为: 对话, 分支, 消息和附件四个仓储契约.
    这里的方法只做读取和拼装, 不做权限判断, 权限判断由调用方或
    `PublicationServiceContract` 等更高层的契约负责.
    """

    def list_conversations(self, page: Page) -> PageResult[Conversation]:
        """返回一页对话, 供管理员或本地输出端使用

        窗口由调用方给出, 服务层不再提供"不传就返回全部"的隐式路径:
        那等于把无界查询留在架构里
        """
        ...

    def list_published_conversations(self, page: Page) -> PageResult[Conversation]:
        """返回一页已发布的对话, 供普通用户或公开输出端使用"""
        ...

    def get_conversation(self, conversation_source_id: str) -> Conversation | None:
        """根据来源 ID 获取一个对话的基本信息"""
        ...

    def get_conversation_detail(
        self,
        conversation_source_id: str,
    ) -> ConversationDetail | None:
        """获取对话, 分支, 消息和附件组成的完整详情"""
        ...

    def get_message(self, message_source_id: str) -> Message | None:
        """根据来源 ID 获取一条消息

        供需要先确认消息存在, 再挂载互动数据的调用方使用, 避免它们绕过
        本契约直接访问消息仓储.
        """
        ...

    def get_message_conversation_source_id(
        self,
        message_source_id: str,
    ) -> str | None:
        """查询某条消息所属对话的来源 ID

        消息在库内只挂在分支上, 调用方需要对话归属时通过本方法获取,
        不要自己拼接分支到对话的关系.
        """
        ...

    def list_branches(self, conversation_source_id: str) -> list[Branch]:
        """获取某个对话下的分支列表"""
        ...

    def list_messages(
        self,
        branch_source_id: str,
        page: Page,
    ) -> PageResult[Message]:
        """获取某个分支下按 position 排序的一页消息"""
        ...

    def list_attachments(self, message_source_id: str) -> list[Attachment]:
        """获取某条消息下的附件列表"""
        ...

    def list_attachments_for_messages(
        self,
        message_source_ids: list[str],
    ) -> dict[str, list[Attachment]]:
        """一次获取多条消息下的附件, 按消息来源 ID 分组返回

        供分页展示场景使用: 一页消息可能有几十条, 逐条查询会产生几十次
        查询, 而这里只需要 1 次
        """
        ...


__all__ = [
    "ConversationDetail",
    "QueryingServiceContract",
]