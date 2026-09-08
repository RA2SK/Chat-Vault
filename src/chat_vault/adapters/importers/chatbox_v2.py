"""针对Chatbox 1.22及以上版本的输入适配器"""

from pathlib import Path
from typing import Iterator
import zipfile
import json
from .base import BaseImporter, ParseResult

class ChatboxV2Importer(BaseImporter):
    format_key = "chatbox.v2"

    def detect(self, path: Path) -> bool:
        """判断文件是否为 Chatbox v2 备份。"""

        if not zipfile.is_zipfile(path):
            return False

        try:
            with zipfile.ZipFile(path) as archive:
                if "manifest.json" not in archive.namelist():
                    return False

                manifest = json.loads(
                    archive.read("manifest.json").decode("utf-8")
                )

                return (
                    manifest.get("format") == "chatbox-backup"
                    and manifest.get("formatVersion") == 2
                    and manifest.get("application", {}).get("name") == "Chatbox"
                )
            
        except (
            OSError, 
            zipfile.BadZipFile,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return False

    def parse(self, path: Path) -> Iterator[ParseResult]:
        """解析 Chatbox 备份，并逐个产出解析结果。"""
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(
                    archive.read("manifest.json").decode("utf-8")
                )
        except (
            OSError, 
            zipfile.BadZipFile,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            yield ParseResult(
                error=f"无法读取 manifest.json: {exc}",
                source_ref=str(path),
            )
            return

        sessions = manifest.get("sessions")

        if not isinstance(sessions, list):
            yield ParseResult(
                error="manifest.json 中缺少有效的 sessions 列表",
                source_ref="manifest.json",
            )
            return

        for session_info in sessions:
            if not isinstance(session_info, dict):
                yield ParseResult(
                    error="会话索引项不是有效对象",
                    source_ref="manifest.json",
                )
                continue