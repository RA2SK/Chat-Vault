"""定义前端请求, 响应和公开数据结构的校验格式

本模块是 HTTP 与业务服务之间的形状转换层, 只做两件事:

- 把请求体校验成业务服务能接受的输入 (``to_*`` 方法)
- 把业务服务的返回值转换成响应体 (``from_*`` 类方法)

刻意不做的事情:

- 不做权限判断. 权限规则属于业务规则, 由服务层执行, 这里只负责把当前用户
  透传下去
- 不直接暴露领域模型. 领域模型带有 ``source_archive``, ``import_batch_id``,
  ``password_hash`` 这类内部字段, 直接返回会把内部结构泄露给前端. 每个响应
  模型都逐字段列举允许暴露的内容, 领域模型以后新增字段时不会因为疏忽被
  自动带出去
- 不重复定义枚举. ``core.enums`` 下的枚举都是 ``str`` 子类, 可以直接作为
  字段类型, 前端拿到的就是枚举值字符串

错误响应不在这里定义成模型, 而是由 ``api/exception_handlers.py`` 直接构造
``{"error": {"key": ..., "message": ...}}``. 异常处理器是异常体系唯一的翻译点,
把错误形状再声明一遍会形成第二处需要同步维护的定义.
"""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from core.enums import CommentTarget, ImportStatus, MarkType, MessageRole, UserRole
from core.models import AdminMark, Comment, Conversation, ImportBatch
from modules.interfaces.comments_intf import CommentSubmission
from modules.interfaces.publishing_intf import (
    PublishedConversationSummary,
    PublishedConversationView,
    PublishedMessageView,
)
from modules.interfaces.users_intf import UserView

T = TypeVar("T")

__all__ = [
    "AdminRegisterRequest",
    "CommentCreateRequest",
    "CommentResponse",
    "ConversationDetailResponse",
    "ConversationSummaryResponse",
    "ImportRequest",
    "ImportResponse",
    "LoginRequest",
    "MarkCreateRequest",
    "MarkResponse",
    "MessageResponse",
    "PageResponse",
    "PasswordChangeRequest",
    "UserResponse",
]


# === 分页信封 ===


class PageResponse(BaseModel, Generic[T]):
    """分页响应信封

    刻意用信封而不是裸数组: 裸数组里没有位置放 ``has_more``, 前端只能靠
    "返回条数是否等于 limit" 来猜还有没有下一页, 而最后一页恰好装满时
    这个猜测是错的.

    也刻意不用 ``X-Total-Count`` 这类响应头: 响应头在浏览器里需要额外配置
    CORS 暴露规则, 而且 OpenAPI 文档无法描述它, 前端拿不到类型信息.
    """

    items: list[T]
    limit: int
    offset: int
    has_more: bool


# === 请求模型 ===


class CommentCreateRequest(BaseModel):
    """创建评论的请求体

    ``nickname`` 允许匿名展示名, 缺省值与契约中的默认值保持一致
    """

    target_type: CommentTarget
    target_source_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    nickname: str = "anonymous"

    def to_submission(self) -> CommentSubmission:
        """转换成评论服务接受的输入形状"""

        return CommentSubmission(
            target_type=self.target_type,
            target_source_id=self.target_source_id,
            content=self.content,
            nickname=self.nickname,
        )


class LoginRequest(BaseModel):
    """登录请求体"""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AdminRegisterRequest(BaseModel):
    """创建管理员的请求体

    刻意不提供角色字段: 本接口只创建管理员, 普通用户注册走 ``register``,
    让角色由接口路径决定而不是由请求体决定, 前端就无法通过改一个字段提权
    """

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
    """修改密码的请求体"""

    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class MarkCreateRequest(BaseModel):
    """为消息添加管理员标记的请求体

    刻意不携带消息标识: 消息标识由接口路径给出, 同一个值有两个来源时,
    两者不一致的处理方式会成为一处需要长期维护的分支
    """

    mark_type: MarkType


class ImportRequest(BaseModel):
    """导入备份文件的请求体

    接收服务器本地路径而不是上传的文件内容: 当前部署形态是本地运行, 备份文件
    本来就在同一台机器上, 走路径可以避免把整个备份读进内存再落盘. 待部署到
    网站后需要上传能力时, 再补一个接收文件流的接口, 而不是把本接口改造成
    两种输入混在一起
    """

    path: str = Field(min_length=1)
    format_key: str | None = None


# === 响应模型 ===


class MessageResponse(BaseModel):
    """展示场景下的一条消息"""

    source_id: str
    role: MessageRole
    content: str
    position: int
    model: str | None = None
    timestamp: datetime | None = None
    edited_at: datetime | None = None
    attachments: list[str] = Field(default_factory=list)

    @classmethod
    def from_view(cls, view: PublishedMessageView) -> "MessageResponse":
        """从展示视图构造响应"""

        return cls(
            source_id=view.source_id,
            role=view.role,
            content=view.content,
            position=view.position,
            model=view.model,
            timestamp=view.timestamp,
            edited_at=view.edited_at,
            attachments=list(view.attachments),
        )


class ConversationSummaryResponse(BaseModel):
    """对话列表项"""

    source_id: str
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_view(
        cls,
        view: PublishedConversationSummary,
    ) -> "ConversationSummaryResponse":
        """从展示视图构造响应"""

        return cls(
            source_id=view.source_id,
            title=view.title,
            created_at=view.created_at,
            updated_at=view.updated_at,
        )

    @classmethod
    def from_model(cls, conversation: Conversation) -> "ConversationSummaryResponse":
        """从领域模型构造响应

        发布和隐藏接口返回的是领域模型, 它带有 `source_archive`,
        `source_entry` 和 `import_batch_id`. 逐字段列举允许暴露的内容,
        领域模型以后新增字段时不会因为疏忽被自动带出去.
        """

        return cls(
            source_id=conversation.source_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class ConversationDetailResponse(BaseModel):
    """对话详情, 含当前链上的消息"""

    source_id: str
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: list[MessageResponse] = Field(default_factory=list)

    @classmethod
    def from_view(
        cls,
        view: PublishedConversationView,
    ) -> "ConversationDetailResponse":
        """从展示视图构造响应"""

        return cls(
            source_id=view.source_id,
            title=view.title,
            created_at=view.created_at,
            updated_at=view.updated_at,
            messages=[MessageResponse.from_view(message) for message in view.messages],
        )


class CommentResponse(BaseModel):
    """一条评论"""

    id: str
    target_type: CommentTarget
    content: str
    nickname: str
    created_at: datetime | None = None
    conversation_source_id: str | None = None
    message_source_id: str | None = None

    @classmethod
    def from_model(cls, comment: Comment) -> "CommentResponse":
        """从领域模型构造响应

        刻意不返回 ``created_by``: 评论对外以 ``nickname`` 展示, 用户标识属于
        内部信息, 暴露它会让前端有能力把同一用户在不同对话下的发言关联起来
        """

        return cls(
            id=comment.id,
            target_type=comment.target_type,
            content=comment.content,
            nickname=comment.nickname,
            created_at=comment.created_at,
            conversation_source_id=comment.conversation_source_id,
            message_source_id=comment.message_source_id,
        )


class UserResponse(BaseModel):
    """对外暴露的用户信息"""

    id: str
    username: str
    role: UserRole
    created_at: datetime | None = None

    @classmethod
    def from_view(cls, view: UserView) -> "UserResponse":
        """从用户视图构造响应"""

        return cls(
            id=view.id,
            username=view.username,
            role=view.role,
            created_at=view.created_at,
        )


class MarkResponse(BaseModel):
    """一条管理员标记"""

    id: str
    message_source_id: str
    mark_type: MarkType
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, mark: AdminMark) -> "MarkResponse":
        """从领域模型构造响应"""

        return cls(
            id=mark.id,
            message_source_id=mark.message_source_id,
            mark_type=mark.mark_type,
            created_at=mark.created_at,
        )


class ImportResponse(BaseModel):
    """一次导入的结果"""

    id: str
    file_name: str
    format_key: str
    status: ImportStatus
    total_count: int
    success_count: int
    failed_count: int
    error_summary: str | None = None

    @classmethod
    def from_model(cls, batch: ImportBatch) -> "ImportResponse":
        """从导入批次模型构造响应

        刻意不返回 ``file_hash``: 它是去重用的内部指纹, 前端不需要, 返回它
        等于把"这份文件是否已导入过"变成一个可被外部探测的接口
        """

        return cls(
            id=batch.id,
            file_name=batch.file_name,
            format_key=batch.format_key,
            status=batch.status,
            total_count=batch.total_count,
            success_count=batch.success_count,
            failed_count=batch.failed_count,
            error_summary=batch.error_summary,
        )
