"""对外部原始数据执行通用的预处理, 清洗和标准化操作"""

from core.enums import SourceType
from core.exceptions import ValidationError
from core.messages import MessageKey

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
        TypeError: 参数类型不正确时抛出. 这是调用方的编程错误, 不是业务状况,
            因此刻意保持为内置 TypeError, 不带提示键, 出口层也不翻译它
        ValidationError: 下列任一情况抛出, 各自带不同的提示键:
            来源名称或原始标识为空 (SOURCE_NAMESPACE_EMPTY);
            原始标识首尾带空白 (SOURCE_NAMESPACE_RAW_PADDED);
            来源名称含空白字符 (SOURCE_NAMESPACE_WHITESPACE);
            来源名称含命名空间分隔符 (SOURCE_NAMESPACE_SEPARATOR)

    来源名称取自 ``SourceType.value``. 枚举取值一律使用不含空白的短横杠形式
    (例如 ``"cherry-studio"``), 因为前缀里出现空格会让 ``source_id`` 的切分
    产生歧义. 前缀要用作命名空间时, 需要的是不含空白的标识符, 而不是展示用的
    名称. 空白字符那一条校验保留下来, 用于拦住将来新增的、取值带空格的枚举.
    """

    if not isinstance(source_type, SourceType) or not isinstance(raw_source_id, str):
        raise TypeError(
            "source_type 必须是 SourceType, raw_source_id 必须是字符串"
        )

    source_name = source_type.value

    if not source_name or not raw_source_id:
        raise ValidationError(MessageKey.SOURCE_NAMESPACE_EMPTY)

    if raw_source_id != raw_source_id.strip():
        raise ValidationError(MessageKey.SOURCE_NAMESPACE_RAW_PADDED)

    if any(character.isspace() for character in source_name):
        raise ValidationError(
            MessageKey.SOURCE_NAMESPACE_WHITESPACE,
            source_name=source_name,
        )

    if SOURCE_ID_SEPARATOR in source_name:
        raise ValidationError(
            MessageKey.SOURCE_NAMESPACE_SEPARATOR,
            separator=repr(SOURCE_ID_SEPARATOR),
        )

    return f"{source_name}{SOURCE_ID_SEPARATOR}{raw_source_id}"
