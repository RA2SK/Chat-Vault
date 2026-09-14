"""运维域模型, 描述程序运行过程本身产生的记录"""

from dataclasses import dataclass, field
from datetime import datetime

from core.enums import ImportStatus, SourceType
from core.types import ImportBatchId, new_id


@dataclass
class ImportBatch:
    """导入批次模型, 记录每次导入操作的结果"""

    file_name: str
    file_hash: str                                  # 整个备份文件的 SHA-256, 识别重复导入
    started_at: datetime
    status: ImportStatus                            # "success" | "partial" | "failed"
    total_count: int
    success_count: int
    failed_count: int

    source_type: SourceType = SourceType.CHATBOX
    format_key: str = "chatbox.v2"                  # 程序内部格式识别码, 与导入适配器对应
    error_summary: str | None = None
    finished_at: datetime | None = None
    id: ImportBatchId = field(default_factory=lambda: ImportBatchId(new_id()))
