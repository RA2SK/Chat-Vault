"""针对Chatbox 1.22及以上版本的输入适配器"""

from pathlib import Path, PurePosixPath
from typing import Iterator, cast
from datetime import datetime, timezone
import zipfile
import json

from .base import BaseImporter, ParseResult
from chat_vault.core.models import Attachment, Branch, Checksum, Conversation, Message

"""需要维护的全局变量"""
EMPTY_THINKING_MARKERS = {"", "[redacted]"}     # 用于清理思考链的空值标记, 避免在导入时显示无意义的思考内容



class ChatboxV2Importer(BaseImporter):
    format_key = "chatbox.v2"

    def detect(self, path: Path) -> bool:
        """判断文件是否为 Chatbox v2 备份"""

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
                    and application.get("name") == "Chatbox"
                )

        except (
            OSError,
            zipfile.BadZipFile,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return False



    def parse(self, path: Path) -> Iterator[ParseResult]:
        """解析 Chatbox 备份, 并逐个产出解析结果"""

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

                # === 读取 session, 并统一收集 conversation 和 thread ===
                sessions = manifest.get("sessions")
                if not isinstance(sessions, list):
                    yield ParseResult(
                        error="会话索引项中缺少有效的 sessions 列表",
                        source_ref="manifest.json",
                    )
                    return
                
                session_items: list[dict[str, object]] = []     # 列表内容为所有的 conversation 和 thread

                for session_info in sessions:                   # 第一层大循环

                    # === 进行各项验证 ===
                    if not isinstance(session_info, dict):
                        yield ParseResult(
                            error="会话索引项不是有效对象",
                            source_ref="manifest.json",
                        )
                        continue

                    source_id = session_info.get("id")
                    session_path = session_info.get("path")
                    if not isinstance(source_id, str) or not source_id:
                        yield ParseResult(
                            error="会话索引项缺少有效的 id",
                            source_ref="manifest.json",
                        )
                        continue
                    if not isinstance(session_path, str) or not session_path:
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
                    if session_data.get("id") != source_id:
                        yield ParseResult(
                            error="会话索引项中的会话 id 与会话的 id 不一致",
                            source_id=source_id,
                            source_ref=session_path,
                        )
                        continue

                    # 将 conversation 加入列表
                    session_items.append(
                        {
                            "kind": "conversation",
                            "source_id": source_id,
                            "title": title,
                            "source_entry": session_path,
                            "messages": messages,
                            "message_forks_hash": session_data.get(
                                "messageForksHash", {}
                            ),
                            "collection_warnings": [],
                        }
                    )

                    collection_warnings = cast(
                        list[str], session_items[-1]["collection_warnings"]
                    )
                    threads = session_data.get("threads", [])

                    # === 进行各项验证 ===
                    if not isinstance(threads, list):
                        collection_warnings.append(
                            "会话中的 threads 不是有效列表, 已忽略"
                        )
                        continue

                    for thread_position, thread_data in enumerate(threads):
                        if not isinstance(thread_data, dict):
                            collection_warnings.append(
                                f"第 {thread_position} 个 thread 不是有效对象, 已跳过"
                            )
                            continue

                        thread_origin_id = thread_data.get("id")
                        thread_name = thread_data.get("name")
                        thread_messages = thread_data.get("messages")
                        if not isinstance(thread_origin_id, str) or not thread_origin_id:
                            collection_warnings.append(
                                f"第 {thread_position} 个 thread 缺少有效的 id, 已跳过"
                            )
                            continue
                        if not isinstance(thread_name, str):
                            collection_warnings.append(
                                f"thread {thread_origin_id} 缺少有效的 name, 已跳过"
                            )
                            continue
                        if not isinstance(thread_messages, list):
                            collection_warnings.append(
                                f"thread {thread_origin_id} 缺少有效的 messages 列表, 已跳过"
                            )
                            continue

                        thread_id = f"{source_id}::thread::{thread_origin_id}"

                        # 将 thread 加入列表
                        session_items.append(
                            {
                                "kind": "thread",
                                "source_id": thread_id,
                                "title": thread_name,
                                "source_entry": session_path,
                                "messages": thread_messages,
                                "message_forks_hash": {},
                            }
                        )

                # === 开始循环处理列表内的 conversation 和 thread ===
                for session_item in session_items:                                  # 第二层大循环

                    # === 从列表中读取一个元素 ===
                    item_source_id = cast(str, session_item["source_id"])
                    item_title = cast(str, session_item["title"])
                    item_source_entry = cast(str, session_item["source_entry"])
                    item_messages = cast(list[object], session_item["messages"])
                    item_forks = session_item["message_forks_hash"]

                    conversation = Conversation(
                        source_id=item_source_id,
                        title=item_title,
                        source_entry=item_source_entry,
                    )
                    warnings: list[str] = cast(
                        list[str], session_item.get("collection_warnings", [])
                    )

                    main_branch = self._parse_branch(
                        branch_source_id=f"{item_source_id}::main",
                        branch_index=0,
                        fork_message_source_id=None,
                        messages=item_messages,
                        resource_by_storage_key=resource_by_storage_key,
                        archive_names=archive_names,
                        warnings=warnings,
                        is_current=True,
                    )
                    if main_branch is not None:
                        conversation.branches.append(main_branch)

                    if isinstance(item_forks, dict):
                        self._parse_fork_branches(
                            conversation=conversation,
                            message_forks_hash=item_forks,
                            resource_by_storage_key=resource_by_storage_key,
                            archive_names=archive_names,
                            warnings=warnings,
                        )
                    elif item_forks is not None:
                        warnings.append(
                            "会话中的 messageForksHash 不是有效对象, 已忽略"
                        )

                    # === 汇总所有 Branch 的时间范围 ===
                    branch_timestamps = [
                        timestamp
                        for branch in conversation.branches
                        for timestamp in (branch.created_at, branch.updated_at)
                        if timestamp is not None
                    ]
                    conversation.created_at = (
                        min(branch_timestamps) if branch_timestamps else None
                    )
                    conversation.updated_at = (
                        max(branch_timestamps) if branch_timestamps else None
                    )

                    # 每个元素独立解析之后逐个 yield
                    yield ParseResult(
                        conversation=conversation,
                        source_id=item_source_id,
                        source_ref=item_source_entry,
                        warnings=warnings,
                    )
                return

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



    def _parse_branch(
        self,
        branch_source_id: str,
        branch_index: int,
        fork_message_source_id: str | None,
        messages: list[object],
        resource_by_storage_key: dict[str, dict],
        archive_names: set[str],
        warnings: list[str],
        is_current: bool = False,
    ) -> Branch:
        """循环解析单条消息链, 调用 _parse_message 和 _parse_attachment, 返回分支链对象 Branch """

        branch = Branch(
            source_id=branch_source_id,
            index=branch_index,
            fork_message_source_id=fork_message_source_id,
            is_current=is_current,
        )

        valid_position = 0                              # 消息在链中的实际位置
        for message_data in messages:                   # 第三层大循环

            # === 进行各项验证 ===
            if not isinstance(message_data, dict):
                warnings.append(
                    f"分支 {branch_source_id} 的消息不是有效对象, 已跳过"
                )
                continue

            message_id = message_data.get("id")
            role = message_data.get("role")
            content_parts = message_data.get("contentParts")

            if not isinstance(message_id, str) or not message_id:
                warnings.append(
                    f"分支 {branch_source_id} 的消息缺少有效的 id, 已跳过"
                )
                continue

            if not isinstance(role, str) or not role:
                warnings.append(
                    f"分支 {branch_source_id} 的消息 {message_id} 缺少有效的 role, 已跳过"
                )
                continue

            if not isinstance(content_parts, list):
                warnings.append(
                    f"分支 {branch_source_id} 的消息 {message_id} 缺少有效的 contentParts, 已跳过"
                )
                continue

            parsed_message = self._parse_message(       # 调用函数处理单条消息
                content_parts=content_parts,
                message_id=message_id,
                message_data=message_data,
                role=role,
                position=valid_position,
                resource_by_storage_key=resource_by_storage_key,
                archive_names=archive_names,
                warnings=warnings,
            )
            message, attachments = parsed_message
            branch.messages.append(message)
            valid_position += 1

            for attachment in attachments:              # 整理本条链下各个消息所携带的附件
                self._parse_attachment(
                    branch=branch,
                    attachment=attachment,
                    warnings=warnings,
                )

        timestamps = [
            message.timestamp
            for message in branch.messages
            if message.timestamp is not None
        ]
        branch.created_at = min(timestamps) if timestamps else None
        branch.updated_at = max(timestamps) if timestamps else None

        return branch



    def _parse_fork_branches(
        self,
        conversation: Conversation,
        message_forks_hash: dict[str, object],
        resource_by_storage_key: dict[str, dict],
        archive_names: set[str],
        warnings: list[str],
    ) -> None:
        """传播式解析 messageForksHash 中全部分支并调用 _parse_branch 函数进行处理"""

        # === 以主链和已经解析的分支共同构成当前 Conversation 的已知消息集合 ===
        known_message_ids = {
            message.source_id
            for branch in conversation.branches
            for message in branch.messages
        }
        pending_forks = dict(message_forks_hash)
        
        while pending_forks:                                        # 分支可能继续以自身消息作为下一个分支的锚点, 因此需要多轮处理
            resolved_fork = False

            for fork_message_source_id, fork_data in list(pending_forks.items()):

                # === 验证分支是否在当前对话中 ===
                if (
                    not isinstance(fork_message_source_id, str)
                    or not fork_message_source_id
                ):
                    warnings.append(
                        "messageForksHash 中存在无效的分叉消息 id, 已跳过"
                    )
                    del pending_forks[fork_message_source_id]       # 删除集合中无效的分支

                    resolved_fork = True
                    continue

                if fork_message_source_id not in known_message_ids: # 分支的头不在当前对话内
                    continue

                if not isinstance(fork_data, dict):
                    warnings.append(
                        f"分叉消息 {fork_message_source_id} 的数据不是有效对象, 已跳过"
                    )
                    del pending_forks[fork_message_source_id]

                    resolved_fork = True
                    continue

                # === 确认分支属于当前对话，进行其他验证 ===
                branch_list = fork_data.get("lists")
                if not isinstance(branch_list, list):
                    warnings.append(
                        f"分叉消息 {fork_message_source_id} 缺少有效的 lists 列表, 已跳过"
                    )
                    del pending_forks[fork_message_source_id]
                    resolved_fork = True
                    continue

                for branch_index, branch_data in enumerate(branch_list):
                    if not isinstance(branch_data, dict):
                        warnings.append(
                            f"分叉消息 {fork_message_source_id} 的第 "
                            f"{branch_index} 个分支不是有效对象, 已跳过"
                        )
                        continue

                    branch_source_id = branch_data.get("id")
                    branch_messages = branch_data.get("messages")
                    if not isinstance(branch_source_id, str) or not branch_source_id:
                        warnings.append(
                            f"分叉消息 {fork_message_source_id} 的第 "
                            f"{branch_index} 个分支缺少有效的 id, 已跳过"
                        )
                        continue
                    if not isinstance(branch_messages, list):
                        warnings.append(
                            f"分支 {branch_source_id} 缺少有效的 messages 列表, 已跳过"
                        )
                        continue

                    # === 调用函数解析通过的分支链 ===
                    branch = self._parse_branch(
                        branch_source_id=branch_source_id,
                        branch_index=branch_index,
                        fork_message_source_id=fork_message_source_id,
                        messages=branch_messages,
                        resource_by_storage_key=resource_by_storage_key,
                        archive_names=archive_names,
                        warnings=warnings,
                        is_current=False,
                    )
                    conversation.branches.append(branch)

                    for message in branch.messages:
                        known_message_ids.add(message.source_id)

                del pending_forks[fork_message_source_id]
                resolved_fork = True

            if not resolved_fork:                           # 无法确定分支的头所归属的对话
                for unresolved_fork_id in pending_forks:
                    warnings.append(
                        f"分叉消息 {unresolved_fork_id} 无法找到所属的消息, 已跳过"
                    )
                break



    def _parse_message(
        self,
        content_parts: list[object],
        message_id: str,
        message_data: dict[str, object],
        role: str,
        position: int,
        resource_by_storage_key: dict[str, dict],
        archive_names: set[str],
        warnings: list[str],
    ) -> tuple[Message, list[Attachment]]:
        """解析单条消息, 调用 _parse_message_part_ 系列辅助函数, 返回消息对象 Message 及附件对象 Attachment"""

        text_parts: list[str] = []                                  # 待拼接的正文列表
        thinking_parts: list[str] = []                              # 待拼接的思考内容列表
        attachments: list[Attachment] = []                          # 本条消息下的附件列表

        for part_index, part in enumerate(content_parts):           # 第四层大循环
            if not isinstance(part, dict):
                warnings.append(
                    f"消息 {message_id} 的第 {part_index} 个内容片段不是有效对象, 已跳过"
                )
                continue

            # === 调用不同的辅助函数处理不同类型的片段 ===
            part_type = part.get("type")
            match part_type:
                case "text":                                        # 正文
                    text = part.get("text")
                    self._parse_message_part_text(
                        text=text,
                        text_parts=text_parts,
                        message_id=message_id,
                        part_index=part_index,
                        warnings=warnings,
                    )
                case "reasoning":                                   # 思考链
                    thinking = part.get("text")
                    self._parse_message_part_reasoning(
                        thinking=thinking,
                        thinking_parts=thinking_parts,
                        message_id=message_id,
                        part_index=part_index,
                        warnings=warnings,
                    )
                case "info":                                        # 工具链
                    self._parse_message_part_info(
                        message_id=message_id,
                        warnings=warnings,
                    )
                case "image":                                       # 图片
                    storage_key = part.get("storageKey")
                    attachment = self._parse_message_part_image(
                        message_id=message_id,
                        storage_key=storage_key,
                        part_index=part_index,
                        resource_by_storage_key=resource_by_storage_key,
                        archive_names=archive_names,
                        warnings=warnings,
                    )
                    if attachment is not None:
                        attachments.append(attachment)
                case _:                                             # 其他情况, 以后还要加文件分支
                    warnings.append(
                        f"消息 {message_id} 的第 {part_index} 个内容类型 "
                        f"{part_type!r} 暂不支持, 已跳过"
                    )

        # === 拼接正文和思考片段 ===
        text_content = "".join(text_parts)
        thinking_content = "\n".join(thinking_parts)

        # === 提取模型名称 ===
        model_value = message_data.get("model") or message_data.get("modelId")
        ai_provider = message_data.get("aiProvider")
        model_name: str | None = None
        if isinstance(model_value, str):
            model_name = model_value
            if isinstance(ai_provider, str) and ai_provider:
                model_name = f"{ai_provider}/{model_name}"

        # === 提取并转换时间戳格式 ===
        timestamp_value = message_data.get("timestamp")
        timestamp: datetime | None = None
        if (
            isinstance(timestamp_value, (int, float))
            and not isinstance(timestamp_value, bool)
        ):
            try:
                timestamp = datetime.fromtimestamp(
                    timestamp_value / 1000,
                    tz=timezone.utc,
                )
            except (OSError, OverflowError, ValueError) as exc:
                warnings.append(
                    f"消息 {message_id} 的 timestamp 存在问题: {exc}"
                )
        else:
            warnings.append(f"消息 {message_id} 缺少有效的 timestamp")

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



    def _parse_attachment(
        self,
        branch: Branch,
        attachment: Attachment,
        warnings: list[str],
    ) -> None:
        """将附件归属到 Branch"""

        message_source_id = attachment.message_source_id
        if not isinstance(message_source_id, str) or not message_source_id:
            warnings.append("附件缺少有效的 message_source_id, 已跳过")
            return

        message_ids = {message.source_id for message in branch.messages}
        if message_source_id not in message_ids:
            warnings.append(
                f"附件对应的消息 {message_source_id} 不在分支 {branch.source_id} 中, 已跳过"
            )
            return

        branch.attachments.append(attachment)



    def _parse_message_part_text(
        self,
        text: object,
        text_parts: list[str],
        message_id: str,
        part_index: int,
        warnings: list[str],
    ) -> None:
        """提取消息片段中的正文并加入待拼接列表"""

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
        """提取消息片段中的思考部分, 清理无效内容后加入待拼接列表"""

        if isinstance(thinking, str):
            cleaned_thinking = thinking.strip()
            if cleaned_thinking.lower() not in EMPTY_THINKING_MARKERS:
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
        """忽略消息中的 info 片段并记录警告"""

        warnings.append(f"消息 {message_id} 的 info 片段被自动忽略")



    def _parse_message_part_image(
        self,
        message_id: str,
        storage_key: object,
        part_index: int,
        resource_by_storage_key: dict[str, dict],
        archive_names: set[str],
        warnings: list[str],
    ) -> Attachment | None:
        """解析 image 片段并创建附件"""

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
            warnings.append(f"消息 {message_id} 的 image 资源缺少有效的 path")
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
                checksum = {"algorithm": algorithm, "value": value}

        return Attachment(
            attach_type="image",
            source_ref=resource_path,
            mime_type=mime_type,
            checksum=checksum,
            size=size,
            message_source_id=message_id,
        )

    
