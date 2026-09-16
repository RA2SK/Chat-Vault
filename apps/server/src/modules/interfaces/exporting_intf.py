"""输出能力契约, 定义把已发布内容重新打包成外部可读形式的调用约定

输出能力与输入适配器对称: 输入适配器把外部备份解析成核心模型, 输出能力
把核心模型整理成外部文件. 两侧都以 `format_key` 作为格式身份.

输出能力的输入一律是展示视图 `PublishedConversationView`, 而不是
`ConversationDetail`. 这样输出端拿不到思考内容, 原始备份位置和导入批次
等内部字段, 重新打包时不会把内部信息带到外部文件里.

目前没有任何输出端实现, 本模块只声明形状.
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

from modules.interfaces.publishing_intf import PublishedConversationView


@runtime_checkable
class ContentExporter(Protocol):
    """内容输出端的结构契约

    `format_key` 是输出格式的身份, 用于选择输出端和记录导出批次;
    `file_suffix` 用于生成默认文件名, 不含前导点号.
    """

    format_key: str
    file_suffix: str

    def export(self, view: PublishedConversationView) -> bytes | str:
        """把一个展示视图重新打包成一个外部文件的内容"""
        ...


@runtime_checkable
class ExportingService(Protocol):
    """输出能力契约

    调用方给出一批对话的来源 ID 和输出端, 由实现完成权限过滤, 内容整理,
    重新打包和落盘的编排. 具体实现尚未开始.
    """

    def export_conversation(
        self,
        conversation_source_id: str,
        exporter: ContentExporter,
        target_dir: Path,
    ) -> Path:
        """把一个对话重新打包并写入目标目录, 返回实际写入的文件路径

        对话不存在时抛出 NotFoundError, 输出端与内容不兼容时抛出 ValidationError.
        本契约不接收当前用户, 权限判断由调用方在更外层完成.
        """
        ...


__all__ = [
    "ContentExporter",
    "ExportingService",
]