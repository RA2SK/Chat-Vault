"""Chatbox v2 会话时间字段测试。"""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chat_vault.adapters.importers.chatbox_v2 import ChatboxV2Importer


def make_backup(tmp_path: Path, timestamps: list[object]) -> Path:
    """创建只包含时间字段的最小 Chatbox v2 测试备份。"""
    session_id = "test-session"
    session_path = "sessions/test-session/session.json"
    messages = [
        {
            "id": f"message-{index}",
            "role": "user",
            "contentParts": [{"type": "text", "text": "测试消息"}],
            "timestamp": timestamp,
        }
        for index, timestamp in enumerate(timestamps)
    ]
    manifest = {
        "format": "chatbox-backup",
        "formatVersion": 2,
        "application": {"name": "Chatbox"},
        "sessions": [{"id": session_id, "path": session_path}],
    }
    session = {"id": session_id, "name": "时间测试", "messages": messages}
    backup_path = tmp_path / "time-test.zip"

    with zipfile.ZipFile(backup_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(session_path, json.dumps(session))

    return backup_path


def parse_single_conversation(backup_path: Path):
    """解析测试备份，并断言只产生一个会话结果。"""
    results = list(ChatboxV2Importer().parse(backup_path))
    assert len(results) == 1
    assert results[0].error is None
    assert results[0].conversation is not None
    return results[0]


def test_conversation_time_range_uses_earliest_and_latest_timestamp(tmp_path: Path):
    backup_path = make_backup(tmp_path, [2000, 1000, 3000])

    result = parse_single_conversation(backup_path)

    assert result.conversation.created_at == datetime.fromtimestamp(
        1, tz=timezone.utc
    )
    assert result.conversation.updated_at == datetime.fromtimestamp(
        3, tz=timezone.utc
    )


def test_conversation_time_range_ignores_invalid_timestamp(tmp_path: Path):
    backup_path = make_backup(tmp_path, [2000, "invalid", True])

    result = parse_single_conversation(backup_path)

    expected = datetime.fromtimestamp(2, tz=timezone.utc)
    assert result.conversation.created_at == expected
    assert result.conversation.updated_at == expected
    assert len(result.warnings) == 2


def test_conversation_time_range_is_none_when_all_timestamps_are_invalid(
    tmp_path: Path,
):
    backup_path = make_backup(tmp_path, ["invalid", True, None])

    result = parse_single_conversation(backup_path)

    assert result.conversation.created_at is None
    assert result.conversation.updated_at is None
    assert len(result.warnings) == 3


def test_timestamp_overflow_is_reported_as_warning(tmp_path: Path):
    backup_path = make_backup(tmp_path, [10**100])

    result = parse_single_conversation(backup_path)

    assert result.conversation.created_at is None
    assert result.conversation.updated_at is None
    assert len(result.warnings) == 1
    assert "timestamp 存在问题" in result.warnings[0]
