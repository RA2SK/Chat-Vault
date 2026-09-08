"""针对Chatbox 1.22及以上版本的输入适配器"""

from pathlib import Path
from typing import Iterator
from datetime import datetime, timezone
import zipfile
import json
from .base import BaseImporter, ParseResult
from chat_vault.core.models import Conversation, Message

"""需要维护的全局变量"""
EMPTY_THINKING_MARKERS = {"", "[redacted]"} # 用于清理思考链的空值标记，避免在导入时显示无意义的思考内容


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
                if not isinstance(manifest, dict):
                    return False

                application = manifest.get("application")
                if not isinstance(application, dict):
                    return False

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

                # === 开始进行 manifest.json 的解析 ===
                manifest = json.loads(
                    archive.read("manifest.json").decode("utf-8")
                )
                if not isinstance(manifest, dict):
                    yield ParseResult(
                        error="会话索引项顶层结构不是有效的 JSON 对象",
                        source_ref="manifest.json",
                    )
                    return

                sessions = manifest.get("sessions")

                if not isinstance(sessions, list):
                    yield ParseResult(
                        error="会话索引项中缺少有效的 sessions 列表",
                        source_ref="manifest.json",
                    )
                    return

                # === 开始进行 session.json 的解析 ===
                for session_info in sessions:
                    if not isinstance(session_info, dict):
                        yield ParseResult(
                            error="会话索引项不是有效对象",
                            source_ref="manifest.json",
                        )
                        continue

                    source_id = session_info.get("id")
                    session_path = session_info.get("path")

                    if not isinstance(source_id,str) or not source_id:
                        yield ParseResult(
                            error="会话索引项缺少有效的 id",
                            source_ref="manifest.json",
                        )
                        continue

                    if not isinstance(session_path,str) or not session_path:
                        yield ParseResult(
                            error="会话索引项缺少有效的 path",
                            source_ref="manifest.json",
                        )
                        continue

                    try:
                        session_data = json.loads(
                            archive.read(session_path).decode("utf-8")
                        )
                    except (
                        KeyError,
                        ValueError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ) as exc:
                        yield ParseResult(
                            error=f"无法读取会话文件: {exc}",
                            source_id=source_id,
                            source_ref=session_path,
                        )
                        continue


                    if not isinstance(session_data, dict):
                        yield ParseResult(
                            error="会话顶层结构不是有效的 JSON 对象",
                            source_id=source_id,
                            source_ref=session_path,
                        )
                        continue               

                    title = session_data.get("name")
                    messages = session_data.get("messages")

                    if not isinstance(title, str):
                        yield ParseResult(
                            error="会话中缺少有效的 name",
                            source_id=source_id,
                            source_ref=session_path,
                        )
                        continue

                    if not isinstance(messages, list):
                        yield ParseResult(
                            error="会话中缺少有效的 messages 列表",
                            source_id=source_id,
                            source_ref=session_path,
                        )
                        continue

                    session_data_id = session_data.get("id")
                    if session_data_id != source_id:
                        yield ParseResult(
                            error="会话索引项中的会话 id 与会话的 id 不一致",
                            source_id=source_id,
                            source_ref=session_path,
                        )
                        continue

                    # === 对session.json的对话部分的解析成功，通过各项验证，可以建立对话对象 ===
                    conversation = Conversation(
                        source_id=source_id,
                        title=title,
                        source_entry=session_path,
                    )

                    warnings: list[str] = []

                    # === 开始解析消息列表，进行必要的验证 ===
                    for position, message_data in enumerate(messages):
                        if not isinstance(message_data, dict):
                            warnings.append(
                                f"第 {position} 条消息不是有效对象，已跳过"
                            )
                            continue

                        message_id = message_data.get("id")
                        role = message_data.get("role")
                        content_parts = message_data.get("contentParts")

                        if not isinstance(message_id, str) or not message_id:
                            warnings.append(
                                f"第 {position} 条消息缺少有效的 id，已跳过"
                            )
                            continue

                        if not isinstance(role, str) or not role:
                            warnings.append(
                                f"第 {position} 条消息缺少有效的 role，已跳过"
                            )
                            continue

                        if not isinstance(content_parts, list):
                            warnings.append(
                                f"第 {position} 条消息缺少有效的 contentParts，已跳过"
                            )
                            continue

                        # === 验证结束，从 contentParts 中提取 text 和 thinking ，并忽略其他内容 ===
                        text_parts: list[str] = []
                        thinking_parts: list[str] = []

                        for part_index, part in enumerate(content_parts):
                            if not isinstance(part, dict):
                                warnings.append(
                                    f"消息 {message_id} 的第 {part_index} 个内容片段不是有效对象，已跳过"
                                )
                                continue

                            part_type = part.get("type")

                            match part_type:        # 处理不同类型的内容片段，已用match-case语句替代if-elif-else
                                case "text":
                                    text = part.get("text")

                                    if isinstance(text, str):
                                        text_parts.append(text)
                                    else:
                                        warnings.append(
                                            f"消息 {message_id} 的第 {part_index} 个 text 片段缺少有效文本"
                                        )

                                case "reasoning":
                                    thinking = part.get("text")

                                    if isinstance(thinking, str):
                                        cleaned_thinking = thinking.strip()

                                        if cleaned_thinking not in EMPTY_THINKING_MARKERS:
                                            thinking_parts.append(cleaned_thinking)

                                    else:
                                        warnings.append(
                                            f"消息 {message_id} 的第 {part_index} 个 reasoning 片段缺少有效文本"
                                        )

                                case "info":
                                    warnings.append(
                                        f"消息 {message_id} 的 info 片段被自动忽略"
                                    )

                                case "image":
                                    warnings.append(
                                        f"消息 {message_id} 的 image 片段暂未处理"
                                    )

                                case _:
                                    warnings.append(
                                        f"消息 {message_id} 的第 {part_index} 个内容类型 "
                                        f"{part_type!r} 暂不支持，已跳过"
                                    )

                        # === 读取其他消息字段并进行 text 和 thinking 的合并 ===
                        text_content = "".join(text_parts)
                        thinking_content = "\n".join(thinking_parts)

                        model_value = message_data.get("model") or message_data.get("modelId")
                        ai_provider = message_data.get("aiProvider")
                        model_name: str | None = None

                        if isinstance(model_value, str):
                            model_name = model_value
                            if isinstance(ai_provider, str) and ai_provider:
                                model_name = f"{ai_provider}/{model_name}"

                        timestamp_value = message_data.get("timestamp")
                        timestamp: datetime | None = None

                        if isinstance(timestamp_value, (int, float)):
                            timestamp = datetime.fromtimestamp(
                                timestamp_value / 1000,
                                tz=timezone.utc,
                            )
                        else:
                            warnings.append(
                                f"消息 {message_id} 缺少有效的 timestamp"
                            )

                        # === 创建消息对象并添加到对话中 ===
                        message = Message(
                            source_id=message_id,
                            role=role,
                            content=text_content,
                            position=position,
                            thinking=thinking_content,
                            model=model_name,
                            timestamp=timestamp,
                        )

                        conversation.messages.append(message)

                        # === 一切正常情况下的迭代器输出 ===
                        yield ParseResult(
                            conversation=conversation,
                            source_id=source_id,
                            source_ref=session_path,
                            warnings=warnings,
                        )

                    

        except (
            OSError, 
            zipfile.BadZipFile,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            yield ParseResult(
                error=f"无法读取或解析 Chatbox v2 备份: {exc}",
                source_ref=str(path),
            )
            return



