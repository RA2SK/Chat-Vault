"""集中定义业务标识符, 通用别名和跨模块共享的基础类型结构"""

from dataclasses import dataclass
from typing import NewType, TypedDict
from uuid import uuid4

from core.enums import SourceType


def new_id() -> str:
    """生成互动域和运维域使用的应用侧标识符"""

    return uuid4().hex


class Checksum(TypedDict):
    """资源去重使用的校验值"""

    algorithm: str
    value: str


CommentId = NewType("CommentId", str)
AdminMarkId = NewType("AdminMarkId", str)
MessageRevisionId = NewType("MessageRevisionId", str)
UserId = NewType("UserId", str)
ImportBatchId = NewType("ImportBatchId", str)


@dataclass(frozen=True)
class SourceRef:
    """导入内容的稳定身份, 用于幂等去重, 不随重复导入改变"""

    source_type: SourceType
    native_id: str


@dataclass(frozen=True)
class Provenance:
    """导入内容的溯源信息, 重复导入时可被新的备份文件覆盖"""

    archive: str
    entry: str | None = None