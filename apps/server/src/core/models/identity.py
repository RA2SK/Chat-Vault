"""身份域模型, 描述访问系统的各类用户主体"""

from dataclasses import dataclass, field
from datetime import datetime

from core.enums import UserRole
from core.types import UserId, new_id


@dataclass
class User:
    """用户信息模型, 包括普通用户和管理员"""

    username: str
    password_hash: str                              # 禁止明文
    created_at: datetime

    role: UserRole = UserRole.ADMIN
    id: UserId = field(default_factory=lambda: UserId(new_id()))
