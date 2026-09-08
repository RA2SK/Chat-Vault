"""定义输入适配器的接口并承载返回的ParseResult"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from chat_vault.core.models import Conversation

@dataclass
class ParseResult:
    """适配器 parse() 的单个产出"""

    conversation: Conversation | None = None
    error: str | None = None
    source_id: str | None = None
    source_ref: str | None = None
    warnings: list[str] = field(default_factory=list)

class BaseImporter:
    """输入适配器的接口"""

    format_key: str                   # 适配器类型注解

    def detect(self, path: Path) -> bool:
        """判断给定文件是否是当前适配器支持的格式"""
        raise NotImplementedError 

    def parse(self, path: Path) -> Iterator[ParseResult]:
        """解析给定文件，返回一个迭代器，迭代器每次返回一个 ParseResult"""
        raise NotImplementedError

    