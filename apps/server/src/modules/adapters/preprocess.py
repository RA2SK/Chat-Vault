"""对外部原始数据执行通用的预处理, 清洗和标准化操作"""

from core.enums import SourceType

SOURCE_ID_SEPARATOR = ":"


def with_source_namespace(source_type: SourceType, raw_source_id: str) -> str:
    """为外部 source_id 添加来源前缀

    例如'chatbox:session-123'
    ``raw_source_id`` 内部可能包含 ``::`` 等层级分隔符, 函数只在最前面
    添加来源前缀, 不会修改原始 ID 的其他部分

    Args:
        source_type: 输入来源的枚举值, 例如 ``SourceType.CHATBOX``
        raw_source_id: 输入文件中的原始实体 ID
    Raises:
        TypeError: 参数类型不正确时抛出
        ValueError: 参数为空、包含空白, 或来源名称含有命名空间分隔符时抛出
    """

    if not isinstance(source_type, SourceType) or not isinstance(raw_source_id, str):
        raise TypeError("source_type 必须是 SourceType, raw_source_id 必须是字符串")

    source_name = source_type.value

    if not source_name or not raw_source_id:
        raise ValueError("source_type 和 raw_source_id 不能为空")

    if raw_source_id != raw_source_id.strip():
        raise ValueError("raw_source_id 不能以空白字符开头或结尾")

    if any(character.isspace() for character in source_name):
        raise ValueError("source_type 不能包含空白字符")

    if SOURCE_ID_SEPARATOR in source_name:
        raise ValueError(
            f"source_type 不能包含命名空间分隔符 {SOURCE_ID_SEPARATOR!r}"
        )

    return f"{source_name}{SOURCE_ID_SEPARATOR}{raw_source_id}"
