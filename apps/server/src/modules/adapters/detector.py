"""根据文件内容, 来源信息或格式特征识别适用的输入适配器"""

from pathlib import Path

# from . import REGISTRY

def detect_format(path: Path) -> str | None:
    """检测文件格式, 返回匹配的 format_key"""

    from . import REGISTRY  # 避免循环导入

    for adapter_class in REGISTRY.values():
        importer = adapter_class()
        if importer.detect(path):
            return adapter_class.format_key

    return None
