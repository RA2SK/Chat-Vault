"""登记可用的输入适配器, 并提供按格式键或按文件内容选择适配器的统一入口

适配器的选择逻辑放在这里而不是各自的调用方: 命令行入口和 Web 入口都需要
"按格式键取适配器"和"按文件内容猜适配器"这两件事, 各写一份会让新增适配器时
漏改其中一处. 选择逻辑只依赖注册表, 不依赖任何调用方的输入形状, 因此放在
适配器包内是合适的.
"""

from pathlib import Path

from core.exceptions import ImportFailedError
from core.messages import MessageKey
from modules.adapters.base import BaseImporter
from modules.adapters.chatbox_v2 import ChatboxV2Importer

__all__ = [
    "REGISTRY",
    "detect_importer",
    "resolve_importer",
]

REGISTRY: dict[str, type[BaseImporter]] = {
    ChatboxV2Importer.format_key: ChatboxV2Importer,
}


def resolve_importer(format_key: str) -> BaseImporter:
    """按格式键取适配器实例

    未知格式键抛出 ImportFailedError 而不是 KeyError: 命令行入口用 argparse 的
    ``choices`` 约束取值, 非法值到不了这里; Web 入口的格式键来自请求体, 必须
    有明确的业务异常, 否则会变成 500.
    """

    importer_class = REGISTRY.get(format_key)
    if importer_class is None:
        raise ImportFailedError(
            MessageKey.IMPORT_FORMAT_MISMATCH,
            path="",
            format_key=", ".join(sorted(REGISTRY)),
        )

    return importer_class()


def detect_importer(path: Path) -> BaseImporter:
    """按注册顺序找到一个能识别该文件的适配器

    先校验路径本身, 再交给适配器识别. 文件不存在时若直接进入识别流程,
    适配器读不到内容, 最终会报成"格式不匹配", 把"文件不存在"误诊成"格式不对".
    命令行入口和 Web 入口都从这里选适配器, 校验放在这里两边同时受益.

    没有任何适配器识别该文件时抛出 ImportFailedError.
    """

    path = Path(path)

    if not path.exists():
        raise ImportFailedError(MessageKey.IMPORT_FILE_NOT_FOUND, path=path)

    if not path.is_file():
        raise ImportFailedError(MessageKey.IMPORT_PATH_NOT_FILE, path=path)

    for importer_class in REGISTRY.values():
        importer = importer_class()
        if importer.detect(path):
            return importer

    raise ImportFailedError(
        MessageKey.IMPORT_FORMAT_MISMATCH,
        path=path,
        format_key=", ".join(sorted(REGISTRY)),
    )
