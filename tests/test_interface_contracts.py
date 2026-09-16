"""接口契约的运行时冒烟检查

这些用例只验证"具体实现是否具备契约要求的方法名", 不验证签名是否一致.
签名一致性由 pyright 负责, 因为 isinstance 只比较方法名.

因此本文件的失败必然意味着契约被破坏, 本文件的通过不能证明契约完全被满足.
"""

from pathlib import Path

import pytest

from bootstrap import ServiceContainer
from modules.interfaces.comments_intf import CommentServiceContract
from modules.interfaces.importing_intf import ImportServiceContract, ParseResult
from modules.interfaces.moderation_intf import ModerationServiceContract
from modules.interfaces.publishing_intf import PublicationServiceContract
from modules.interfaces.querying_intf import ConversationDetail, QueryingServiceContract
from modules.interfaces.users_intf import UserView


@pytest.fixture
def container(tmp_path: Path) -> ServiceContainer:
    service_container = ServiceContainer.create(
        database_path=tmp_path / "contracts.db",
        initialize=False,
    )
    yield service_container
    service_container.close()


def test_container_services_satisfy_contracts(container: ServiceContainer) -> None:
    assert isinstance(container.import_service, ImportServiceContract)
    assert isinstance(container.query_service, QueryingServiceContract)
    assert isinstance(container.publishing_service, PublicationServiceContract)
    assert isinstance(container.moderation_service, ModerationServiceContract)
    assert isinstance(container.comment_service, CommentServiceContract)


def test_migrated_dtos_are_re_exported_from_original_locations() -> None:
    from modules.adapters.base import ParseResult as AdapterParseResult
    from modules.services.querying import (
        ConversationDetail as ServiceConversationDetail,
    )

    assert AdapterParseResult is ParseResult
    assert ServiceConversationDetail is ConversationDetail


def test_user_view_does_not_expose_password_hash() -> None:
    assert "password_hash" not in UserView.__dataclass_fields__


def test_interface_package_exports_every_name_in_dunder_all() -> None:
    from modules import interfaces

    for name in interfaces.__all__:
        assert getattr(interfaces, name) is not None
