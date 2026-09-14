"""输入适配器共用的 source_id 命名空间工具

适配器从外部文件读取的 ID 只在外部格式中有意义写入统一模型前, 
应为它添加来源命名空间, 避免不同输入来源使用相同 ID 时发生冲突
"""


SOURCE_ID_SEPARATOR = ":"


def with_source_namespace(source_type: str, raw_source_id: str) -> str:
    """为外部 source_id 添加来源前缀

    例如'chatbox_v2:session-123'
    ``raw_source_id`` 内部可能包含 ``::`` 等层级分隔符, 函数只在最前面
    添加来源前缀, 不会修改原始 ID 的其他部分

    Args:
        source_type: 输入来源的稳定名称, 例如 ``"chatbox_v2"``
        raw_source_id: 输入文件中的原始实体 ID
    Raises:
        TypeError: 参数不是字符串时抛出
        ValueError: 参数为空、包含空白, 或 source_type 含有命名空间分隔符时抛出
    """

    if not isinstance(source_type, str) or not isinstance(raw_source_id, str):
        raise TypeError("source_type 和 raw_source_id 必须是字符串")

    if not source_type or not raw_source_id:
        raise ValueError("source_type 和 raw_source_id 不能为空")

    if source_type != source_type.strip() or raw_source_id != raw_source_id.strip():
        raise ValueError("source_type 和 raw_source_id 不能以空白字符开头或结尾")

    if any(character.isspace() for character in source_type):
        raise ValueError("source_type 不能包含空白字符")

    if SOURCE_ID_SEPARATOR in source_type:
        raise ValueError(
            f"source_type 不能包含命名空间分隔符 {SOURCE_ID_SEPARATOR!r}"
        )

    return f"{source_type}{SOURCE_ID_SEPARATOR}{raw_source_id}"
