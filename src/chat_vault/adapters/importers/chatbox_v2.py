"""针对Chatbox 1.22及以上版本的输入适配器"""

from pathlib import Path, PurePosixPath
from typing import Iterator
from datetime import datetime, timezone
import zipfile
import json
from .base import BaseImporter, ParseResult
from chat_vault.core.models import Conversation, Message, Attachment, Checksum

"""需要维护的全局变量"""
EMPTY_THINKING_MARKERS = {"", "[REDACTED]"}     # 用于清理思考链的空值标记, 避免在导入时显示无意义的思考内容


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
        """解析 Chatbox 备份, 并逐个产出解析结果。"""

        try:
            with zipfile.ZipFile(path) as archive:
                archive_names = set(archive.namelist())

                # === 进行 manifest.json 的解析 ===
                manifest = json.loads(
                    archive.read("manifest.json").decode("utf-8")
                )
                if not isinstance(manifest, dict):
                    yield ParseResult(
                        error="会话索引项顶层结构不是有效的 JSON 对象",
                        source_ref="manifest.json",
                    )
                    return

                # === 进行 resources 的解析 ===
                resources = manifest.get("resources", [])
                resource_by_storage_key: dict[str, dict] = {}

                if isinstance(resources, list):
                    for resource in resources:
                        if not isinstance(resource, dict): 
                            continue

                        resource_keys = resource.get("originalStorageKeys", [])
                        if not isinstance(resource_keys, list): 
                            continue

                        for storage_key in resource_keys:
                            if isinstance(storage_key, str) and storage_key:
                                resource_by_storage_key[storage_key] = resource

                # === 进行 session.json 的解析 ===
                sessions = manifest.get("sessions")

                if not isinstance(sessions, list):
                    yield ParseResult(
                        error="会话索引项中缺少有效的 sessions 列表",
                        source_ref="manifest.json",
                    )
                    return
                
                for session_info in sessions:

                    # === 进行各项验证 ===
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

                    # === 建立对话对象并调用辅助函数解析消息列表 ===
                    conversation = Conversation(
                        source_id=source_id,
                        title=title,
                        source_entry=session_path,
                    )

                    warnings: list[str] = []

                    self._parse_messages(
                        conversation=conversation,
                        messages=messages,
                        resource_by_storage_key=resource_by_storage_key,
                        archive_names=archive_names,
                        warnings=warnings,
                    )

                    # === 验证 threads, 并暂存有效的线程数据 ===
                    threads = session_data.get("threads", [])
                    valid_threads: list[tuple[str, str, list[object]]] = []

                    if not isinstance(threads, list):
                        warnings.append(
                            "会话中的 threads 不是有效列表，已忽略"
                        )
                    else:
                        for thread_position, thread_data in enumerate(threads):
                            if not isinstance(thread_data, dict):
                                warnings.append(
                                    f"第 {thread_position} 个 thread 不是有效对象，已跳过"
                                )
                                continue

                            thread_id = thread_data.get("id")
                            thread_name = thread_data.get("name")
                            thread_messages = thread_data.get("messages")

                            if not isinstance(thread_id, str) or not thread_id:
                                warnings.append(
                                    f"第 {thread_position} 个 thread 缺少有效的 id，已跳过"
                                )
                                continue

                            if not isinstance(thread_name, str):
                                warnings.append(
                                    f"thread {thread_id} 缺少有效的 name，已跳过"
                                )
                                continue

                            if not isinstance(thread_messages, list):
                                warnings.append(
                                    f"thread {thread_id} 缺少有效的 messages 列表，已跳过"
                                )
                                continue

                            valid_threads.append(
                                (thread_id, thread_name, thread_messages)
                            )

                    # === 为线程派生会话创建独立的 Conversation ===
                    for thread_id, thread_name, thread_messages in valid_threads:
                        thread_conversation = Conversation(
                            source_id=f"{source_id}::thread::{thread_id}",
                            title=thread_name,
                            source_entry=session_path,
                        )

                        thread_warnings: list[str] = []

                        self._parse_messages(
                            conversation=thread_conversation,
                            messages=thread_messages,
                            resource_by_storage_key=resource_by_storage_key,
                            archive_names=archive_names,
                            warnings=thread_warnings,
                        )

                        # === 线程派生会话的迭代器输出 ===
                        yield ParseResult(
                            conversation=thread_conversation,
                            source_id=thread_conversation.source_id,
                            source_ref=session_path,
                            warnings=thread_warnings,
                        )

                    # === 正常会话的迭代器输出 ===
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



    def _parse_messages(
        self,
        conversation: Conversation,
        messages: list[object],
        resource_by_storage_key: dict[str, dict[str, object]],
        archive_names: set[str],
        warnings: list[str],
    ) -> None:
        """循环解析消息, 组织各辅助函数返回值并补充至 Conversation 的辅助函数"""
        earliest_timestamp: datetime | None = None
        latest_timestamp: datetime | None = None

        for position, message_data in enumerate(messages):

            # === 进行各项验证 ===
            if not isinstance(message_data, dict):
                warnings.append(
                    f"第 {position} 条消息不是有效对象, 已跳过"
                )
                continue
        
            message_id = message_data.get("id")
            role = message_data.get("role")
            content_parts = message_data.get("contentParts")
        
            if not isinstance(message_id, str) or not message_id:
                warnings.append(
                    f"第 {position} 条消息缺少有效的 id, 已跳过"
                )
                continue
        
            if not isinstance(role, str) or not role:
                warnings.append(
                    f"第 {position} 条消息缺少有效的 role, 已跳过"
                )
                continue
        
            if not isinstance(content_parts, list):
                warnings.append(
                    f"第 {position} 条消息缺少有效的 contentParts, 已跳过"
                )
                continue
        
            # === 调用辅助函数处理单条消息 ===
            parsed = self._parse_one_message(
                content_parts=content_parts, 
                message_id=message_id, 
                message_data=message_data, 
                role=role, 
                position=position, 
                resource_by_storage_key=resource_by_storage_key, 
                archive_names=archive_names, 
                warnings=warnings
            )
        
            # === 将处理好的单条消息添加至对话内 ===
            message, attachments = parsed
        
            conversation.messages.append(message)
            conversation.attachments.extend(attachments)
        
            if message.timestamp is not None:
                if earliest_timestamp is None or message.timestamp < earliest_timestamp:
                    earliest_timestamp = message.timestamp
                if latest_timestamp is None or message.timestamp > latest_timestamp:
                    latest_timestamp = message.timestamp
        
        # === 更新对话的时间戳信息 ===
        conversation.created_at = earliest_timestamp
        conversation.updated_at = latest_timestamp



    def _parse_one_message(
        self,
        content_parts: list[object],
        message_id: str,
        message_data: dict[str, object],
        role: str,
        position: int,
        resource_by_storage_key: dict[str, dict[str, object]],
        archive_names: set[str],
        warnings: list[str],
    ) -> tuple[Message, list[Attachment]]:
        """解析单条消息并组装成 message 的辅助函数"""
        
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        attachments: list[Attachment] = []                      # 过渡，避免对外部的 conversation 产生依赖
        image_display_index = 0
        
        for part_index, part in enumerate(content_parts):       # 循环解析每个 contentPart
            if not isinstance(part, dict):
                warnings.append(
                    f"消息 {message_id} 的第 {part_index} 个内容片段不是有效对象, 已跳过"
                )
                continue
        
            part_type = part.get("type")
        
            match part_type:                                    # 处理不同类型的内容片段, 已用 match-case 语句替代 if-elif-else
                case "text":
                    text = part.get("text")
        
                    self._parse_message_part_text(
                        text=text, 
                        text_parts=text_parts, 
                        message_id=message_id, 
                        part_index=part_index, 
                        warnings=warnings
                    )
        
                case "reasoning":
                    thinking = part.get("text")
        
                    self._parse_message_part_reasoning(
                        thinking=thinking, 
                        thinking_parts=thinking_parts, 
                        message_id=message_id, 
                        part_index=part_index, 
                        warnings=warnings
                    )
        
                case "info":
                    self._parse_message_part_info(
                        message_id=message_id,
                        warnings=warnings
                    )
        
                case "image":
                    storage_key = part.get("storageKey")
        
                    attachment = self._parse_message_part_attachment(
                            image_display_index=image_display_index, 
                            message_id=message_id, 
                            storage_key=storage_key, 
                            part_index=part_index, 
                            resource_by_storage_key=resource_by_storage_key, 
                            archive_names=archive_names, 
                            warnings=warnings
                        )
                    if attachment is None:
                        continue
        
                    attachments.append(attachment)              # 此处不得直接依赖外层的 conversation
                    image_display_index += 1
        
                case _:
                    warnings.append(
                        f"消息 {message_id} 的第 {part_index} 个内容类型 "
                        f"{part_type!r} 暂不支持, 已跳过"
                    )
        
        # === 进行 text 和 thinking 的合并 ===
        text_content = "".join(text_parts)
        thinking_content = "\n".join(thinking_parts)

        # === 提取并拼接 model ===
        model_value = message_data.get("model") or message_data.get("modelId")
        ai_provider = message_data.get("aiProvider")
        model_name: str | None = None
        
        if isinstance(model_value, str):
            model_name = model_value
            if isinstance(ai_provider, str) and ai_provider:
                model_name = f"{ai_provider}/{model_name}"

        # === 提取 timestamp 并进行验证 ===
        timestamp_value = message_data.get("timestamp")
        timestamp: datetime | None = None
        
        if (
            isinstance(timestamp_value, (int, float))
            and not isinstance(timestamp_value, bool)  # 排除布尔值
        ):
            try:
                timestamp = datetime.fromtimestamp(
                    timestamp_value / 1000,
                    tz=timezone.utc,
                )
            except (OSError, OverflowError, ValueError) as exc:
                timestamp = None
                warnings.append(
                    f"消息 {message_id} 的 timestamp 存在问题: {exc}"
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

        return message, attachments

    

    def _parse_message_part_text(
        self,
        text: object,
        text_parts: list[str],
        message_id: str,
        part_index: int,
        warnings: list[str],
    ) -> None:
        """用于提取消息片段中的正文并进行拼接的辅助函数"""
        
        if isinstance(text, str):
            text_parts.append(text)
        else:
            warnings.append(
                f"消息 {message_id} 的第 {part_index} 个 text 片段缺少有效文本"
            )



    def _parse_message_part_reasoning(
        self,
        thinking: object,
        thinking_parts: list[str],
        message_id: str,
        part_index: int,
        warnings: list[str],
    ) -> None:
        """用于提取消息片段中的思考部分并去除无效内容的辅助函数"""
        
        if isinstance(thinking, str):
            cleaned_thinking = thinking.strip()
        
            if cleaned_thinking not in EMPTY_THINKING_MARKERS:
                thinking_parts.append(cleaned_thinking)
        
        else:
            warnings.append(
                f"消息 {message_id} 的第 {part_index} 个 reasoning 片段缺少有效文本"
            )



    def _parse_message_part_info(
        self,
        message_id: str,
        warnings: list[str],
    ) -> None:
        """用于提取消息片段中的工具链等部分并将其自动忽略的辅助函数"""

        warnings.append(
            f"消息 {message_id} 的 info 片段被自动忽略"
        )



    def _parse_message_part_attachment(
        self,
        image_display_index: int,
        message_id: str,
        storage_key: object,
        part_index: int,
        resource_by_storage_key: dict[str, dict[str, object]],
        archive_names: set[str],
        warnings: list[str],
    ) -> Attachment | None:
        """用于提取消息片段中的图片(或文件), 解析图片内容片段并返回 Attachment, 失败时返回 None 的辅助函数"""
        
        if not isinstance(storage_key, str) or not storage_key:
            warnings.append(
                f"消息 {message_id} 的第 {part_index} 个 image 片段缺少有效的 storageKey"
            )
            return None
        
        resource = resource_by_storage_key.get(storage_key)
        
        if resource is None:
            warnings.append(
                f"消息 {message_id} 的 image 未找到对应资源: {storage_key}"
            )
            return None
        
        resource_path = resource.get("path")
        
        if not isinstance(resource_path, str) or not resource_path:
            warnings.append(
                f"消息 {message_id} 的 image 资源缺少有效的 path"
            )
            return None
        
        resource_path_obj = PurePosixPath(resource_path)
        
        if (
            resource_path_obj.is_absolute() 
            or ".." in resource_path_obj.parts
            or "\\" in resource_path
        ):
            warnings.append(
                f"消息 {message_id} 的 image 资源路径不安全: {resource_path}"
            )
            return None
        
        if resource_path not in archive_names:
            warnings.append(
                f"消息 {message_id} 的 image 资源文件不存在: {resource_path}"
            )
            return None
        
        mime_type = resource.get("mimeType")
        if not isinstance(mime_type, str) or not mime_type:
            mime_type = None
        
        size = resource.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            size = None
        
        checksum_data = resource.get("checksum")
        checksum: Checksum | None = None
        
        if isinstance(checksum_data, dict):
            algorithm = checksum_data.get("algorithm")
            value = checksum_data.get("value")
        
            if (
                isinstance(algorithm, str)
                and algorithm
                and isinstance(value, str)
                and value
            ):
                checksum = {
                    "algorithm": algorithm,
                    "value": value,
                }
        
        attachment = Attachment(
            attach_type="image",
            source_ref=resource_path,
            message_source_id=message_id,
            display_index=image_display_index,
            mime_type=mime_type,
            checksum=checksum,
            size=size,
        )

        return attachment




