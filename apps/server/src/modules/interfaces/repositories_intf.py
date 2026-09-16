"""仓储层契约, 定义业务服务对持久化能力的最小要求

本模块只描述"服务需要仓储做什么", 不描述"仓储如何做到". 因此契约中
不出现数据库连接, SQL 语句和 rowid 等持久化细节.

具体仓储不继承这些协议, 而是依靠结构匹配被动满足: 只要方法名和签名一致,
具体类就被视为符合契约. 调用方依赖契约而非具体实现.

内容域内部用自增 rowid 维持父子外键, rowid 不进入模型也不离开持久化层,
对外一律以 source_id 标识. 需要写父子关系时, 由调用方显式传入父节点的
source_id, 而不是先取出父节点对象.

刻意保留的不对称, 不是遗漏:
- BranchStore 没有 update: 分支只在首次导入时创建
- MessageStore 没有 delete: 消息的移除通过重复导入覆盖实现
- CommentStore / AdminMarkStore 没有 get_by_id: 删除只需 id, 不需要先读取
- CommentStore / AdminMarkStore 只提供软删除: 评论和标记需要保留审计痕迹
- ImportBatchStore 没有按 file_hash 查询的方法, 重复导入检测尚未启用
"""

from typing import Protocol

from core.models import (
    AdminMark,
    Attachment,
    Branch,
    Comment,
    Conversation,
    ImportBatch,
    Message,
    User,
)
from core.types import AdminMarkId, CommentId, ImportBatchId, UserId


class ConversationStore(Protocol):
    """Conversation 的持久化契约"""

    def create(self, conversation: Conversation) -> None:
        """保存一个对话"""
        ...

    def get_by_source_id(self, source_id: str) -> Conversation | None:
        """根据来源 ID 查询对话"""
        ...

    def update(self, conversation: Conversation) -> None:
        """更新一个对话"""
        ...

    def list_all(self) -> list[Conversation]:
        """查询所有对话"""
        ...

    def list_published(self) -> list[Conversation]:
        """查询所有已发布的对话"""
        ...


class BranchStore(Protocol):
    """Branch 的持久化契约"""

    def create(self, branch: Branch, conversation_source_id: str) -> None:
        """保存一个分支, 并挂到指定对话下

        父节点不存在时抛出 ValueError, 而不是等待外键约束在提交时报错
        """
        ...

    def get_by_source_id(self, source_id: str) -> Branch | None:
        """根据来源 ID 查询分支"""
        ...

    def list_by_conversation(self, conversation_source_id: str) -> list[Branch]:
        """查询某个对话下的所有分支, 按 branch_index 升序"""
        ...


class MessageStore(Protocol):
    """Message 的持久化契约"""

    def create(self, message: Message, branch_source_id: str) -> None:
        """保存一条消息, 并挂到指定分支下

        父节点不存在时抛出 ValueError, 而不是等待外键约束在提交时报错
        """
        ...

    def get_by_source_id(self, source_id: str) -> Message | None:
        """根据来源 ID 查询消息"""
        ...

    def get_conversation_source_id(self, message_source_id: str) -> str | None:
        """查询某条消息所属对话的来源 ID, 用于跨内容域引用时确定归属"""
        ...

    def list_by_branch(self, branch_source_id: str) -> list[Message]:
        """查询某个分支下的消息, 按 position 升序"""
        ...

    def update(self, message: Message) -> None:
        """更新一条消息"""
        ...


class AttachmentStore(Protocol):
    """Attachment 的持久化契约

    附件的身份是 (message_source_id, source_ref) 组合, 没有独立的 ID
    """

    def create(self, attachment: Attachment) -> None:
        """保存一个附件"""
        ...

    def list_by_message(self, message_source_id: str) -> list[Attachment]:
        """查询某条消息下的附件"""
        ...

    def update(self, attachment: Attachment) -> None:
        """更新一个附件"""
        ...

    def delete(self, message_source_id: str, source_ref: str) -> None:
        """按附件身份删除一个附件"""
        ...


class CommentStore(Protocol):
    """Comment 的持久化契约

    评论不进入内容图内部, 只按 source_id 引用对话或消息, 不接触 rowid
    """

    def create(self, comment: Comment) -> None:
        """保存一条评论

        target_type 与 conversation_source_id / message_source_id 的组合必须自洽,
        否则抛出 ValueError
        """
        ...

    def list_by_conversation(self, conversation_source_id: str) -> list[Comment]:
        """查询直接挂在某个对话下的评论

        只匹配 conversation_source_id, 不包含该对话所属消息的评论,
        因为消息级评论的 conversation_source_id 为空
        """
        ...

    def list_by_message(self, message_source_id: str) -> list[Comment]:
        """查询某条消息下的评论"""
        ...

    def soft_delete(self, comment_id: CommentId) -> None:
        """软删除一条评论"""
        ...


class AdminMarkStore(Protocol):
    """AdminMark 的持久化契约"""

    def create(self, mark: AdminMark) -> None:
        """保存一个管理员标记"""
        ...

    def list_by_message(self, message_source_id: str) -> list[AdminMark]:
        """查询某条消息下的管理员标记"""
        ...

    def soft_delete(self, mark_id: AdminMarkId) -> None:
        """软删除一个管理员标记"""
        ...


class UserStore(Protocol):
    """User 的持久化契约"""

    def create(self, user: User) -> None:
        """保存一个用户"""
        ...

    def get_by_id(self, user_id: UserId) -> User | None:
        """根据 ID 查询用户"""
        ...

    def get_by_username(self, username: str) -> User | None:
        """根据用户名查询用户"""
        ...

    def update(self, user: User) -> None:
        """更新一个用户"""
        ...


class ImportBatchStore(Protocol):
    """ImportBatch 的持久化契约"""

    def create(self, import_batch: ImportBatch) -> None:
        """保存一个导入批次"""
        ...

    def get_by_id(self, import_batch_id: ImportBatchId) -> ImportBatch | None:
        """根据 ID 查询导入批次"""
        ...

    def update(self, import_batch: ImportBatch) -> None:
        """更新一个导入批次"""
        ...


__all__ = [
    "AdminMarkStore",
    "AttachmentStore",
    "BranchStore",
    "CommentStore",
    "ConversationStore",
    "ImportBatchStore",
    "MessageStore",
    "UserStore",
    ]