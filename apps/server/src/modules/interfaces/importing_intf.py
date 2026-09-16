"""导入能力契约, 定义输入适配器与服务之间, 服务与调用方之间的稳定调用约定

本模块回答两个问题:
- 一个输入适配器必须提供什么, 才能被导入流程接受
- 导入能力对外承诺哪些调用, 输入和输出

`ParseResult` 定义在这里而不是适配器模块, 因为它描述的是"一次解析调用的产出形状",
属于调用契约的一部分. 契约层只能依赖 `core` 和接口层自身, 因此这类结果形状
统一落在接口层, 由具体实现反向引用.

`Importer` 与 `modules/adapters/base.py` 中的 `BaseImporter` 描述同一件事,
两者刻意并存: `Importer` 是结构契约, 供调用方和测试替身使用; `BaseImporter`
是具体适配器继承用的基类, 仍然留在适配器中. 待适配器改为结构匹配后,
`BaseImporter` 会并入接口层.

`ImportServiceContract.import_file` 的参数类型保持为 `BaseImporter`, 而不是收窄成
`Importer`. 函数参数是逆变的, 具体实现接受的就是 `BaseImporter`, 契约若收窄
参数类型, 具体实现反而不再满足契约. 该引用只在类型检查期发生, 以免与
`adapters/base.py` 对 `ParseResult` 的引用形成循环导入.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

from core.enums import SourceType
from core.models import Conversation, ImportBatch

if TYPE_CHECKING:
    from modules.adapters.base import BaseImporter


@dataclass
class ParseResult:
    """一次解析调用的单个产出

    成功时填 `conversation`, 失败时填 `error`, 两者互斥.
    `source_id` 与 `source_ref` 用于把结果回指到原始备份中的位置,
    便于导入批次统计和问题定位.
    """

    conversation: Conversation | None = None
    error: str | None = None
    source_id: str | None = None
    source_ref: str | None = None
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class Importer(Protocol):
    """输入适配器的结构契约

    `format_key` 同时是适配器的身份和导入批次的格式标记, `source_type`
    决定内容 `source_id` 的命名空间前缀, 因此两者都是类属性而不是方法.
    """

    format_key: str
    source_type: SourceType

    def detect(self, path: Path) -> bool:
        """判断给定文件是否是当前适配器支持的格式"""
        ...

    def parse(self, path: Path) -> Iterator[ParseResult]:
        """解析给定文件, 逐个产出解析结果"""
        ...


@runtime_checkable
class ImportServiceContract(Protocol):
    """导入能力契约

    具体实现的构造依赖为: 导入批次, 对话, 分支, 消息和附件五个仓储契约.

    契约只描述调用形状, 不承诺事务边界. 目前 `import_results` 在异常时
    只把批次标记为失败并记录摘要, 已经写入的内容不会回滚.
    """

    def import_file(self, path: Path, importer: BaseImporter) -> ImportBatch:
        """导入一个备份文件, 返回导入批次结果

        适配器与文件不匹配时抛出 ValueError, 文件不存在时抛出 FileNotFoundError.
        """
        ...

    def import_results(
        self,
        path: Path,
        results: Iterator[ParseResult],
        format_key: str = "unknown",
        source_type: SourceType = SourceType.OTHER,
    ) -> ImportBatch:
        """消费适配器产生的解析结果, 返回导入批次结果"""
        ...


__all__ = [
    "Importer",
    "ImportServiceContract",
    "ParseResult",
]