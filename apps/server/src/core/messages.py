"""集中定义面向用户和接口层的提示文本, 实现代码只引用键, 不内联文案

文案散落在各个实现里时, 改一次措辞需要在生产逻辑中做全局文本替换, 加错误码
或多语言更是无从下手. 因此文本集中在本文件, 其他模块只引用 `MessageKey`.

键描述的是"这是什么错误", 而不是"这段代码在哪里". 位置是实现细节, 会随重构
改变; 语义是对外契约的一部分, 不应该改变. 键用符号而不是字符串字面量承载,
于是拼错键会被类型检查直接报出来, 重命名也能由编辑器沿引用一起完成.

需要在抛出点附带变量时使用 `render`, 例如
``render(MessageKey.USER_NOT_FOUND, user_id=user.id)``.

本模块只描述"对用户说什么", 不描述"给开发者记什么". 开发排查用的日志细节
属于 `utils.logging`, 两者刻意分开: 前者稳定且可翻译, 后者详细且随时会变.
"""

from enum import Enum
from string import Formatter

__all__ = [
    "MessageKey",
    "TEXTS",
    "placeholders",
    "render",
    "undeclared_parameters",
]


class MessageKey(str, Enum):
    """业务提示文本的稳定键

    继承 ``str`` 是为了让键可以直接作为字典键, 响应字段和数据库取值使用,
    不需要额外转换. 成员按所属领域分组, 与所在文件位置无关.
    """

    # === 身份与权限 ===
    ADMIN_REQUIRED = "admin_required"
    AUTHENTICATION_REQUIRED = "authentication_required"
    CREDENTIALS_EMPTY = "credentials_empty"
    USERNAME_ALREADY_EXISTS = "username_already_exists"
    USERNAME_INVALID = "username_invalid"
    USERNAME_TOO_LONG = "username_too_long"
    PASSWORD_INVALID = "password_invalid"
    PASSWORD_TOO_LONG = "password_too_long"
    NEW_PASSWORD_EMPTY = "new_password_empty"
    USER_NOT_FOUND = "user_not_found"
    PASSWORD_INCORRECT = "password_incorrect"
    LOGIN_FAILED = "login_failed"

    # === 评论与管理员标记 ===
    COMMENT_CONTENT_EMPTY = "comment_content_empty"
    COMMENT_TARGET_INVALID = "comment_target_invalid"
    COMMENT_CREATE_FORBIDDEN = "comment_create_forbidden"
    COMMENT_CONVERSATION_TARGET_REQUIRED = "comment_conversation_target_required"
    COMMENT_CONVERSATION_TARGET_FORBIDDEN = "comment_conversation_target_forbidden"
    COMMENT_MESSAGE_TARGET_REQUIRED = "comment_message_target_required"
    COMMENT_MESSAGE_TARGET_FORBIDDEN = "comment_message_target_forbidden"
    CONVERSATION_NOT_FOUND = "conversation_not_found"
    MESSAGE_NOT_FOUND = "message_not_found"
    MESSAGE_OWNER_CONVERSATION_NOT_FOUND = "message_owner_conversation_not_found"
    COMMENT_NOT_FOUND = "comment_not_found"
    MARK_NOT_FOUND = "mark_not_found"

    # === 对话, 分支, 消息与附件的结构校验 ===
    CONVERSATION_SOURCE_ID_EMPTY = "conversation_source_id_empty"
    CONVERSATION_TITLE_EMPTY = "conversation_title_empty"
    CONVERSATION_SOURCE_TYPE_EMPTY = "conversation_source_type_empty"
    CONVERSATION_SOURCE_ID_REQUIRED = "conversation_source_id_required"
    CONVERSATION_BRANCH_ANCHOR_MISSING = "conversation_branch_anchor_missing"
    BRANCH_SOURCE_ID_EMPTY = "branch_source_id_empty"
    BRANCH_SOURCE_ID_DUPLICATED = "branch_source_id_duplicated"
    BRANCH_INDEX_NEGATIVE = "branch_index_negative"
    BRANCH_NOT_FOUND = "branch_not_found"
    MESSAGE_SOURCE_ID_EMPTY = "message_source_id_empty"
    MESSAGE_SOURCE_ID_DUPLICATED = "message_source_id_duplicated"
    MESSAGE_POSITION_NEGATIVE = "message_position_negative"
    MESSAGE_POSITION_DUPLICATED = "message_position_duplicated"
    MESSAGE_ROLE_UNSUPPORTED = "message_role_unsupported"
    MESSAGE_ATTACHMENT_ANCHOR_MISSING = "message_attachment_anchor_missing"
    ATTACHMENT_MESSAGE_SOURCE_ID_EMPTY = "attachment_message_source_id_empty"
    ATTACHMENT_MESSAGE_MISMATCH = "attachment_message_mismatch"
    ATTACHMENT_SOURCE_REF_EMPTY = "attachment_source_ref_empty"
    ATTACHMENT_TYPE_UNSUPPORTED = "attachment_type_unsupported"
    ATTACHMENT_SIZE_NEGATIVE = "attachment_size_negative"

    # === 备份文件导入 ===
    IMPORT_FILE_NOT_FOUND = "import_file_not_found"
    IMPORT_PATH_NOT_FILE = "import_path_not_file"
    IMPORT_FORMAT_MISMATCH = "import_format_mismatch"
    IMPORT_RESULT_EMPTY = "import_result_empty"
    IMPORT_CONVERSATION_SAVE_FAILED = "import_conversation_save_failed"

    # === 外部标识符命名空间 ===
    SOURCE_NAMESPACE_EMPTY = "source_namespace_empty"
    SOURCE_NAMESPACE_RAW_PADDED = "source_namespace_raw_padded"
    SOURCE_NAMESPACE_WHITESPACE = "source_namespace_whitespace"
    SOURCE_NAMESPACE_SEPARATOR = "source_namespace_separator"

    # === 持久化 ===
    DATABASE_CONNECTION_FAILED = "database_connection_failed"
    DATABASE_INITIALIZATION_FAILED = "database_initialization_failed"

    # === 请求参数校验 ===
    REQUEST_INVALID = "request_invalid"


TEXTS: dict[MessageKey, str] = {
    MessageKey.ADMIN_REQUIRED: "需要管理员权限",
    MessageKey.AUTHENTICATION_REQUIRED: "需要登录后才能执行此操作",
    MessageKey.CREDENTIALS_EMPTY: "用户名和密码不能为空",
    MessageKey.USERNAME_ALREADY_EXISTS: "用户名 {username} 已存在",
    MessageKey.USERNAME_INVALID: "用户名只能包含字母, 数字, 下划线和连字符",
    MessageKey.USERNAME_TOO_LONG: "用户名长度不能超过 {max_length} 个字符",
    MessageKey.PASSWORD_INVALID: "密码只能包含字母, 数字和常见符号",
    MessageKey.PASSWORD_TOO_LONG: "密码长度不能超过 {max_length} 个字符",
    MessageKey.NEW_PASSWORD_EMPTY: "新密码不能为空",
    MessageKey.USER_NOT_FOUND: "用户 {user_id} 不存在",
    MessageKey.PASSWORD_INCORRECT: "旧密码不正确",
    MessageKey.LOGIN_FAILED: "用户名或密码不正确",

    MessageKey.COMMENT_CONTENT_EMPTY: "评论内容不能为空",
    MessageKey.COMMENT_TARGET_INVALID: "评论目标必须是对话或消息",
    MessageKey.COMMENT_CREATE_FORBIDDEN: "无权在该目标下创建评论",
    MessageKey.COMMENT_CONVERSATION_TARGET_REQUIRED: "对话评论必须设置对话标识",
    MessageKey.COMMENT_CONVERSATION_TARGET_FORBIDDEN: "对话评论不能设置消息标识",
    MessageKey.COMMENT_MESSAGE_TARGET_REQUIRED: "消息评论必须设置消息标识",
    MessageKey.COMMENT_MESSAGE_TARGET_FORBIDDEN: "消息评论不能设置对话标识",
    MessageKey.CONVERSATION_NOT_FOUND: "对话 {conversation_source_id} 不存在",
    MessageKey.MESSAGE_NOT_FOUND: "消息 {message_source_id} 不存在",
    MessageKey.MESSAGE_OWNER_CONVERSATION_NOT_FOUND: (
        "消息 {message_source_id} 所属对话不存在"
    ),
    MessageKey.COMMENT_NOT_FOUND: "评论 {comment_id} 不存在",
    MessageKey.MARK_NOT_FOUND: "标记 {mark_id} 不存在",

    MessageKey.CONVERSATION_SOURCE_ID_EMPTY: "对话标识不能为空",
    MessageKey.CONVERSATION_TITLE_EMPTY: "对话标题不能为空",
    MessageKey.CONVERSATION_SOURCE_TYPE_EMPTY: "对话来源类型不能为空",
    MessageKey.CONVERSATION_SOURCE_ID_REQUIRED: "查找已有对话前必须存在对话标识",
    MessageKey.CONVERSATION_BRANCH_ANCHOR_MISSING: (
        "对话 {conversation_source_id} 不存在, 无法挂载分支"
    ),
    MessageKey.BRANCH_SOURCE_ID_EMPTY: "分支标识不能为空",
    MessageKey.BRANCH_SOURCE_ID_DUPLICATED: (
        "同一对话中存在重复的分支标识: {branch_source_id}"
    ),
    MessageKey.BRANCH_INDEX_NEGATIVE: "分支序号不能小于 0",
    MessageKey.BRANCH_NOT_FOUND: "分支 {branch_source_id} 不存在, 无法挂载消息",
    MessageKey.MESSAGE_SOURCE_ID_EMPTY: "消息标识不能为空",
    MessageKey.MESSAGE_SOURCE_ID_DUPLICATED: (
        "同一分支中存在重复的消息标识: {message_source_id}"
    ),
    MessageKey.MESSAGE_POSITION_NEGATIVE: "消息序号不能小于 0",
    MessageKey.MESSAGE_POSITION_DUPLICATED: (
        "同一分支中存在重复的消息序号: {position}"
    ),
    MessageKey.MESSAGE_ROLE_UNSUPPORTED: "不支持的消息角色: {role}",
    MessageKey.MESSAGE_ATTACHMENT_ANCHOR_MISSING: (
        "消息 {message_source_id} 不存在, 无法挂载附件"
    ),
    MessageKey.ATTACHMENT_MESSAGE_SOURCE_ID_EMPTY: "附件的消息标识不能为空",
    MessageKey.ATTACHMENT_MESSAGE_MISMATCH: (
        "附件引用的消息与所属消息不一致: {message_source_id}"
    ),
    MessageKey.ATTACHMENT_SOURCE_REF_EMPTY: "附件引用标识不能为空",
    MessageKey.ATTACHMENT_TYPE_UNSUPPORTED: "不支持的附件类型: {attach_type}",
    MessageKey.ATTACHMENT_SIZE_NEGATIVE: "附件大小不能小于 0",

    MessageKey.IMPORT_FILE_NOT_FOUND: "导入文件不存在: {path}",
    MessageKey.IMPORT_PATH_NOT_FILE: "导入路径不是文件: {path}",
    MessageKey.IMPORT_FORMAT_MISMATCH: (
        "输入文件格式与适配器不匹配: {path} (format_key={format_key})"
    ),
    MessageKey.IMPORT_RESULT_EMPTY: "解析结果既没有 conversation, 也没有 error",
    MessageKey.IMPORT_CONVERSATION_SAVE_FAILED: "保存会话失败: {reason}",

    MessageKey.SOURCE_NAMESPACE_EMPTY: "来源类型和原始标识不能为空",
    MessageKey.SOURCE_NAMESPACE_RAW_PADDED: "原始标识不能以空白字符开头或结尾",
    MessageKey.SOURCE_NAMESPACE_WHITESPACE: (
        "来源类型不能包含空白字符, 它会被用作来源标识的前缀: {source_name}"
    ),
    MessageKey.SOURCE_NAMESPACE_SEPARATOR: (
        "来源类型不能包含命名空间分隔符 {separator}"
    ),

    MessageKey.DATABASE_CONNECTION_FAILED: "无法建立数据库连接: {reason}",
    MessageKey.DATABASE_INITIALIZATION_FAILED: "数据库初始化失败: {reason}",

    MessageKey.REQUEST_INVALID: "请求参数不合法: {detail}",
}


_FORMATTER = Formatter()


def placeholders(key: MessageKey) -> tuple[str, ...]:
    """列出某个键的文案中出现的占位符名称

    供台账检查和测试使用, 让"文案需要哪些参数"成为可被程序读取的事实,
    而不是只写在注释里.
    """

    names: list[str] = []
    for _, field_name, _, _ in _FORMATTER.parse(TEXTS[key]):
        if field_name:
            names.append(field_name)
    return tuple(names)


def undeclared_parameters(key: MessageKey, **params: object) -> tuple[str, ...]:
    """列出抛出处传了、但文案里没有用到的参数名

    `str.format` 只报缺少参数, 不报多余参数. 调用点改名而文案没跟着改时,
    多余参数会被静默忽略, 于是提示里留下一个没被替换的占位符或一个过时的值.
    把"多余参数"也变成可检查的事实, 才能让这条错误在测试里暴露.
    """

    declared = set(placeholders(key))
    return tuple(name for name in params if name not in declared)


def render(key: MessageKey, **params: object) -> str:
    """按键取出文案并填入参数

    键不存在时直接抛出 ``KeyError``, 因为键由 ``MessageKey`` 限定, 取不到
    只可能是目录缺条目, 属于编程错误而不是运行时状况, 不应该被静默吞掉.

    参数多传时同样报错. ``str.format`` 默认会忽略多余的参数, 于是调用点
    改名后提示里会残留未替换的占位符或者一个过时的值, 而错误只在用户
    看到提示时才被发现. 这里把多余参数也变成 ``TypeError``, 让它在抛出
    点就失败.
    """

    template = TEXTS[key]
    if not params:
        return template

    extra = undeclared_parameters(key, **params)
    if extra:
        raise TypeError(
            f"键 {key.value} 的文案没有声明这些参数: {', '.join(extra)}"
        )

    return template.format(**params)