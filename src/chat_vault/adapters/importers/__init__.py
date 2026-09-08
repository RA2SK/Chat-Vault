from .base import BaseImporter
from .chatbox_v2 import ChatboxV2Importer

REGISTRY: dict[str, type[BaseImporter]] = {
    ChatboxV2Importer.format_key: ChatboxV2Importer,
}