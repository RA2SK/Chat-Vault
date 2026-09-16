"""ImportBatch 的持久化实现"""

import sqlite3
from dataclasses import dataclass

from core.models import ImportBatch
from core.types import ImportBatchId
from modules.repositories.mappings import to_db_datetime, to_import_batch


@dataclass
class ImportBatchRepository:
    """ImportBatch 的持久化接口"""

    connection: sqlite3.Connection

    def create(self, import_batch: ImportBatch) -> None:
        """保存一个导入批次"""

        self.connection.execute(
            """
            INSERT INTO import_batches (
                id,
                file_name,
                file_hash,
                started_at,
                finished_at,
                status,
                total_count,
                success_count,
                failed_count,
                source_type,
                format_key,
                error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_batch.id,
                import_batch.file_name,
                import_batch.file_hash,
                to_db_datetime(import_batch.started_at),
                to_db_datetime(import_batch.finished_at),
                import_batch.status,
                import_batch.total_count,
                import_batch.success_count,
                import_batch.failed_count,
                import_batch.source_type,
                import_batch.format_key,
                import_batch.error_summary,
            ),
        )


    def get_by_id(self, import_batch_id: ImportBatchId) -> ImportBatch | None:
        """根据 ID 查询导入批次"""

        row = self.connection.execute(
            "SELECT * FROM import_batches WHERE id = ?",
            (import_batch_id,),
        ).fetchone()

        if row is None:
            return None

        return to_import_batch(row)


    def get_by_file_hash(self, file_hash: str) -> ImportBatch | None:
        """根据文件内容摘要查询最近一次的导入批次"""

        row = self.connection.execute(
            """
            SELECT *
            FROM import_batches
            WHERE file_hash = ?
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (file_hash,),
        ).fetchone()

        if row is None:
            return None

        return to_import_batch(row)


    def update(self, import_batch: ImportBatch) -> None:
        """更新一个导入批次"""

        self.connection.execute(
            """
            UPDATE import_batches
            SET file_name = ?,
                file_hash = ?,
                started_at = ?,
                finished_at = ?,
                status = ?,
                total_count = ?,
                success_count = ?,
                failed_count = ?,
                source_type = ?,
                format_key = ?,
                error_summary = ?
            WHERE id = ?
            """,
            (
                import_batch.file_name,
                import_batch.file_hash,
                to_db_datetime(import_batch.started_at),
                to_db_datetime(import_batch.finished_at),
                import_batch.status,
                import_batch.total_count,
                import_batch.success_count,
                import_batch.failed_count,
                import_batch.source_type,
                import_batch.format_key,
                import_batch.error_summary,
                import_batch.id,
            ),
        )
