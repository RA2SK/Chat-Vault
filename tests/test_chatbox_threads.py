"""验证 Chatbox v2 threads[] 会被解析为独立会话。"""

import json
import zipfile
from pathlib import Path

from chat_vault.adapters.importers.chatbox_v2 import ChatboxV2Importer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_PATH = PROJECT_ROOT / "data" / "raw" / "chatbox-backup-test.zip"


def test_threads_are_imported_as_separate_conversations() -> None:
    """检查主会话和每个 thread 都只产生一个解析结果。"""
    with zipfile.ZipFile(BACKUP_PATH) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        expected_thread_ids: set[str] = set()
        expected_session_count = 0

        for session_info in manifest["sessions"]:
            session_data = json.loads(archive.read(session_info["path"]))
            expected_session_count += 1
            for thread in session_data.get("threads", []):
                if isinstance(thread, dict) and isinstance(thread.get("id"), str):
                    expected_thread_ids.add(
                        f"{session_info['id']}::thread::{thread['id']}"
                    )

    results = list(ChatboxV2Importer().parse(BACKUP_PATH))
    successful_results = [result for result in results if result.conversation is not None]

    assert not [result for result in results if result.error]
    assert len(successful_results) == expected_session_count + len(expected_thread_ids)

    actual_source_ids = {
        result.conversation.source_id
        for result in successful_results
        if result.conversation is not None
    }
    assert expected_thread_ids <= actual_source_ids

    for result in successful_results:
        conversation = result.conversation
        assert conversation is not None
        assert conversation.source_id
        assert conversation.messages
        assert conversation.created_at is not None
        assert conversation.updated_at is not None
