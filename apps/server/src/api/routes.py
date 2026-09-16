"""定义面向前端的路由, 将 HTTP 请求转换为对应业务服务能够理解的输入并组织响应

本模块只做三件事: 取依赖, 调服务, 把结果交给响应模型. 业务规则一律不写在这里,
权限判断由服务层执行, 本模块只负责把当前用户透传下去.

刻意不做的事情:

- 不直接使用查询能力服务. `QueryingServiceContract` 不做权限判断, 它返回的
  `Conversation` 带有 `source_archive` 和 `import_batch_id`, 用它实现公开读取
  会同时泄露内部字段和未发布的对话. 公开读取一律走发布能力服务
- 不自己判断权限. 路由里写 `if user.role == ...` 会让同一条规则在服务层和
  路由层各有一份, 改一处漏一处
- 不把领域模型直接作为响应. 发布和隐藏接口返回的是领域模型 `Conversation`,
  它带有备份组织和导入批次字段, 因此统一转换成展示列表项再返回
- 不把业务异常翻译成状态码. 那是 `api/exception_handlers.py` 的职责, 这里
  只负责抛出语义正确的异常

当前阶段没有会话和令牌体系, 操作者身份由 `api/dependencies.py` 从请求头解析.
登录接口因此只校验凭据并返回用户信息, 不签发令牌; 待接入真实认证时, 本模块
的接口形状不变, 只是登录接口会多返回一个令牌字段.

管理接口当前不做权限判断, 这是本地部署形态下的有意选择: 前端就是部署者本人,
本来就该有全部权限. 待挂载到网站后, 认证与授权会在服务端自己的界面里完成,
届时给这些接口加上管理员校验即可, 而不是现在先做一个假的校验.
"""

from pathlib import Path

from fastapi import APIRouter, status

from api.dependencies import (
    CommentServiceDep,
    CurrentUserDep,
    ImportServiceDep,
    ModerationServiceDep,
    PublicationServiceDep,
    UserServiceDep,
)
from api.schemas import (
    AdminRegisterRequest,
    CommentCreateRequest,
    CommentResponse,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    ImportRequest,
    ImportResponse,
    LoginRequest,
    MarkCreateRequest,
    MarkResponse,
    PasswordChangeRequest,
    UserResponse,
)
from core.exceptions import NotAuthenticatedError, NotFoundError
from core.messages import MessageKey
from core.types import AdminMarkId, CommentId
from modules.adapters import detect_importer, resolve_importer

__all__ = ["router"]

router = APIRouter(prefix="/api")


# === 公开读取 ===


@router.get(
    "/conversations",
    response_model=list[ConversationSummaryResponse],
    tags=["conversations"],
    summary="列出当前身份可查看的对话",
)
def list_conversations(
    user: CurrentUserDep,
    publishing_service: PublicationServiceDep,
) -> list[ConversationSummaryResponse]:
    """列出当前身份可查看的对话

    管理员看到全部对话, 其他身份只看到已发布的对话. 筛选规则在服务层,
    本接口不重复实现.
    """

    return [
        ConversationSummaryResponse.from_view(summary)
        for summary in publishing_service.list_for_view(user)
    ]


@router.get(
    "/conversations/{conversation_source_id}",
    response_model=ConversationDetailResponse,
    tags=["conversations"],
    summary="获取一个对话的展示详情",
)
def get_conversation(
    conversation_source_id: str,
    user: CurrentUserDep,
    publishing_service: PublicationServiceDep,
) -> ConversationDetailResponse:
    """获取一个对话的展示详情

    无权查看和对话不存在都返回 404, 而不是分别返回 403 和 404. 服务层刻意
    把两种情况统一成 None, 就是为了让调用方无法通过状态码区分"对话不存在"
    和"存在但未发布", 否则未发布的对话标题会被枚举出来.
    """

    view = publishing_service.get_conversation_for_view(user, conversation_source_id)
    if view is None:
        raise NotFoundError(
            MessageKey.CONVERSATION_NOT_FOUND,
            conversation_source_id=conversation_source_id,
        )

    return ConversationDetailResponse.from_view(view)


@router.get(
    "/conversations/{conversation_source_id}/comments",
    response_model=list[CommentResponse],
    tags=["comments"],
    summary="查询一个对话下的全部评论",
)
def list_conversation_comments(
    conversation_source_id: str,
    user: CurrentUserDep,
    publishing_service: PublicationServiceDep,
    comment_service: CommentServiceDep,
) -> list[CommentResponse]:
    """查询一个对话下的全部评论, 含该对话所属消息的评论

    使用合并查询而不是只查直接挂在对话下的评论: 前端要展示的是"这个对话下
    的所有讨论", 只返回对话级评论会让消息级评论在整体视图里消失.

    先按展示权限确认对话可见, 再取评论. 评论服务本身不做权限判断, 直接调用
    会让未发布对话下的评论被读出来, 等于绕过发布状态.
    """

    view = publishing_service.get_conversation_for_view(user, conversation_source_id)
    if view is None:
        raise NotFoundError(
            MessageKey.CONVERSATION_NOT_FOUND,
            conversation_source_id=conversation_source_id,
        )

    return [
        CommentResponse.from_model(comment)
        for comment in comment_service.list_by_conversation_including_messages(
            conversation_source_id,
        )
    ]


# === 评论 ===


@router.post(
    "/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["comments"],
    summary="在对话或消息下发表评论",
)
def create_comment(
    request: CommentCreateRequest,
    user: CurrentUserDep,
    comment_service: CommentServiceDep,
) -> CommentResponse:
    """在对话或消息下发表评论

    请求体整体转换成 `CommentSubmission` 后交给服务层, 而不是把字段拆开传:
    服务层新增字段时只需要改契约和请求模型, 不必再改调用签名.
    """

    comment = comment_service.create(user, request.to_submission())
    return CommentResponse.from_model(comment)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["comments"],
    summary="软删除一条评论",
)
def delete_comment(
    comment_id: str,
    user: CurrentUserDep,
    comment_service: CommentServiceDep,
) -> None:
    """软删除一条评论, 需要管理员权限

    契约只声明软删除, 评论需要保留审计痕迹, 因此本接口不提供物理删除.
    """

    comment_service.delete(user, CommentId(comment_id))


# === 身份 ===


@router.post(
    "/auth/login",
    response_model=UserResponse,
    tags=["auth"],
    summary="校验用户名和密码",
)
def login(
    request: LoginRequest,
    user_service: UserServiceDep,
) -> UserResponse:
    """校验用户名和密码

    认证失败时统一抛出"用户名或密码不正确", 不区分用户不存在和密码错误:
    区分两者会让本接口变成用户名枚举工具.

    当前阶段不签发令牌, 只返回用户信息供前端确认身份. 待接入真实认证后,
    本接口会多返回一个令牌字段, 其余形状不变.
    """

    user = user_service.authenticate(request.username, request.password)
    if user is None:
        raise NotAuthenticatedError(MessageKey.LOGIN_FAILED)

    return UserResponse.from_view(user)


@router.post(
    "/auth/password",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["auth"],
    summary="修改当前身份的密码",
)
def change_password(
    request: PasswordChangeRequest,
    user: CurrentUserDep,
    user_service: UserServiceDep,
) -> None:
    """修改当前身份的密码

    这里的未登录判断是为了把 `UserView | None` 收窄成 `UserView`, 契约要求
    调用方传入已登录用户. 判断结果与服务层内部的 `require_authenticated`
    一致, 因此不会出现两套规则给出不同答案的情况.
    """

    if user is None:
        raise NotAuthenticatedError(MessageKey.AUTHENTICATION_REQUIRED)

    user_service.change_password(user, request.old_password, request.new_password)


# === 管理 ===


@router.post(
    "/admin/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
    summary="创建一个管理员",
)
def register_admin(
    request: AdminRegisterRequest,
    user_service: UserServiceDep,
) -> UserResponse:
    """创建一个管理员

    请求体不提供角色字段: 角色由接口路径决定, 前端就无法通过改一个字段提权.
    """

    user = user_service.register_admin(request.username, request.password)
    return UserResponse.from_view(user)


@router.post(
    "/admin/conversations/{conversation_source_id}/publish",
    response_model=ConversationSummaryResponse,
    tags=["admin"],
    summary="发布一个对话",
)
def publish_conversation(
    conversation_source_id: str,
    user: CurrentUserDep,
    publishing_service: PublicationServiceDep,
) -> ConversationSummaryResponse:
    """发布一个对话, 需要管理员权限

    服务层返回的是领域模型, 这里转换成展示列表项再返回: 领域模型带有
    `source_archive` 和 `import_batch_id`, 直接返回会把内部字段泄露出去.
    """

    conversation = publishing_service.publish(user, conversation_source_id)
    return ConversationSummaryResponse.from_model(conversation)


@router.post(
    "/admin/conversations/{conversation_source_id}/unpublish",
    response_model=ConversationSummaryResponse,
    tags=["admin"],
    summary="隐藏一个对话",
)
def unpublish_conversation(
    conversation_source_id: str,
    user: CurrentUserDep,
    publishing_service: PublicationServiceDep,
) -> ConversationSummaryResponse:
    """隐藏一个对话, 需要管理员权限"""

    conversation = publishing_service.unpublish(user, conversation_source_id)
    return ConversationSummaryResponse.from_model(conversation)


@router.post(
    "/admin/messages/{message_source_id}/marks",
    response_model=MarkResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
    summary="为消息添加管理员标记",
)
def add_mark(
    message_source_id: str,
    request: MarkCreateRequest,
    user: CurrentUserDep,
    moderation_service: ModerationServiceDep,
) -> MarkResponse:
    """为消息添加管理员标记, 需要管理员权限

    消息标识只出现在路径里, 请求体不重复携带: 同一个值有两个来源时, 两者
    不一致的处理方式会成为一处需要长期维护的分支.
    """

    mark = moderation_service.add_mark(user, message_source_id, request.mark_type)
    return MarkResponse.from_model(mark)


@router.get(
    "/admin/messages/{message_source_id}/marks",
    response_model=list[MarkResponse],
    tags=["admin"],
    summary="查询一条消息下的管理员标记",
)
def list_marks(
    message_source_id: str,
    user: CurrentUserDep,
    moderation_service: ModerationServiceDep,
) -> list[MarkResponse]:
    """查询一条消息下的有效管理员标记, 需要管理员权限

    标记是管理员对消息的批注, 属于管理侧数据, 因此不随公开读取接口暴露.
    """

    return [
        MarkResponse.from_model(mark)
        for mark in moderation_service.list_marks(user, message_source_id)
    ]


@router.delete(
    "/admin/marks/{mark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin"],
    summary="软删除一个管理员标记",
)
def remove_mark(
    mark_id: str,
    user: CurrentUserDep,
    moderation_service: ModerationServiceDep,
) -> None:
    """软删除一个管理员标记, 需要管理员权限"""

    moderation_service.remove_mark(user, AdminMarkId(mark_id))


@router.post(
    "/admin/imports",
    response_model=ImportResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
    summary="导入一个备份文件",
)
def import_backup(
    request: ImportRequest,
    import_service: ImportServiceDep,
) -> ImportResponse:
    """导入一个备份文件

    接收服务器本地路径而不是上传的文件内容: 当前部署形态是本地运行, 备份文件
    本来就在同一台机器上, 走路径可以避免把整个备份读进内存再落盘.

    适配器选择复用适配器包提供的统一入口, 而不是在这里重写一遍注册表遍历:
    新增适配器时只需要改注册表, 命令行入口和本接口会同时生效.

    本接口不接收当前用户: 导入能力契约本身不接收用户, 也没有任何权限判断,
    在这里声明一个用不到的身份只会让人误以为它被校验过.
    """

    path = Path(request.path)
    if request.format_key is not None:
        importer = resolve_importer(request.format_key)
    else:
        importer = detect_importer(path)

    batch = import_service.import_file(path, importer)
    return ImportResponse.from_model(batch)
