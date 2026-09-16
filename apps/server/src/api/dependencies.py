"""向路由提供当前用户, 服务实例和请求范围内的运行依赖

本模块是路由与业务服务之间唯一的装配点. 路由不自己构造服务, 也不自己读取
应用状态, 一律通过这里的依赖函数取得, 这样替换实现或调整装配方式时只需要
改本模块.

刻意不提供查询能力服务的依赖函数. `QueryingServiceContract` 不做任何权限
判断, 它返回的 `Conversation` 带有 `source_archive` 和 `import_batch_id`,
直接暴露给前端会同时泄露内部字段和未发布的对话. 公开读取一律走
`PublicationServiceContract`, 不提供入口比写一条注释提醒更难被绕过.

当前用户解析收敛到 `get_current_user` 一个函数. 现阶段没有会话和令牌体系,
前端以 `X-Chat-Vault-User` 请求头声明自己以哪个用户身份操作, 本模块按用户名
查库解析成 `UserView`. 这是本地部署形态下的信任模型: 前端就是部署者本人,
因此允许它自由声明身份.

这不是认证, 也不假装是认证. 待接入真实认证时, 只有本函数的函数体需要改成
解析会话令牌, 签名和所有调用方都不变. 因此这里不提供任何"开发模式管理员
后门": 后门会绕过用户表, 让 `created_by` 指向不存在的用户, 也会在接入认证时
变成必须拆除的隐患. 测试需要固定身份时用
`app.dependency_overrides[get_current_user]` 覆盖本函数.
"""

from typing import Annotated

from fastapi import Depends, Header, Request

from bootstrap import ServiceContainer
from core.exceptions import NotAuthenticatedError
from core.messages import MessageKey
from modules.interfaces.comments_intf import CommentServiceContract
from modules.interfaces.importing_intf import ImportServiceContract
from modules.interfaces.moderation_intf import ModerationServiceContract
from modules.interfaces.publishing_intf import PublicationServiceContract
from modules.interfaces.users_intf import UserServiceContract, UserView

__all__ = [
    "ACTING_USER_HEADER",
    "CommentServiceDep",
    "ContainerDep",
    "CurrentUserDep",
    "ImportServiceDep",
    "ModerationServiceDep",
    "PublicationServiceDep",
    "UserServiceDep",
    "get_comment_service",
    "get_container",
    "get_current_user",
    "get_import_service",
    "get_moderation_service",
    "get_publishing_service",
    "get_user_service",
]

# 前端声明操作者身份的请求头. 名字带前缀是为了不与反向代理或框架自带的
# 请求头冲突, 待接入真实认证后本常量连同解析逻辑一起删除
ACTING_USER_HEADER = "X-Chat-Vault-User"


def get_container(request: Request) -> ServiceContainer:
    """从应用状态取出服务容器

    容器由 `main.py` 的 lifespan 在开始收请求之前放进 `app.state`, 因此这里
    直接取用, 不做存在性判断: 取不到说明 lifespan 没有执行, 属于装配错误,
    让它以 AttributeError 暴露比返回一个空容器更容易定位.
    """

    return request.app.state.container


ContainerDep = Annotated[ServiceContainer, Depends(get_container)]


def get_publishing_service(container: ContainerDep) -> PublicationServiceContract:
    """取得发布能力服务"""

    return container.publishing_service


def get_comment_service(container: ContainerDep) -> CommentServiceContract:
    """取得评论能力服务"""

    return container.comment_service


def get_user_service(container: ContainerDep) -> UserServiceContract:
    """取得用户能力服务"""

    return container.user_service


def get_moderation_service(container: ContainerDep) -> ModerationServiceContract:
    """取得管理能力服务"""

    return container.moderation_service


def get_import_service(container: ContainerDep) -> ImportServiceContract:
    """取得导入能力服务"""

    return container.import_service


PublicationServiceDep = Annotated[
    PublicationServiceContract,
    Depends(get_publishing_service),
]
CommentServiceDep = Annotated[CommentServiceContract, Depends(get_comment_service)]
UserServiceDep = Annotated[UserServiceContract, Depends(get_user_service)]
ModerationServiceDep = Annotated[
    ModerationServiceContract,
    Depends(get_moderation_service),
]
ImportServiceDep = Annotated[ImportServiceContract, Depends(get_import_service)]


def get_current_user(
    container: ContainerDep,
    acting_user: Annotated[str | None, Header(alias=ACTING_USER_HEADER)] = None,
) -> UserView | None:
    """解析当前操作者

    未声明身份时返回 None, 由业务服务按"未登录"处理, 而不是在这里抛异常:
    公开读取接口本来就允许匿名访问, 是否要求登录由各接口自己决定.

    声明了身份但库中查不到该用户时抛出 NotAuthenticatedError. 这里刻意不
    静默退回 None: 用户名写错和"没有声明身份"是两回事, 前者应当立刻报错,
    否则前端只会看到权限不足, 找不到原因.
    """

    if not acting_user:
        return None

    user = container.user_service.get_by_username(acting_user)
    if user is None:
        raise NotAuthenticatedError(MessageKey.AUTHENTICATION_REQUIRED)

    return user


CurrentUserDep = Annotated[UserView | None, Depends(get_current_user)]