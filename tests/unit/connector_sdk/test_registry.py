import asyncio

import pytest

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.errors import (
    ConnectorAuthenticationError,
    ConnectorConfigurationError,
    ConnectorError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ExternalResourceNotFoundError,
    UnsupportedCapabilityError,
)
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.registry import ConnectorRegistry


def test_error_hierarchy() -> None:
    assert issubclass(ConnectorAuthenticationError, ConnectorError)
    assert issubclass(ConnectorConfigurationError, ConnectorError)
    assert issubclass(ConnectorNotFoundError, ConnectorError)
    assert issubclass(ConnectorRateLimitError, ConnectorError)
    assert issubclass(ExternalResourceNotFoundError, ConnectorError)
    assert issubclass(UnsupportedCapabilityError, ConnectorError)


def test_capabilities_frozen() -> None:
    caps = ConnectorCapabilities(
        supports_full_sync=True,
        supports_incremental_sync=False,
        supports_webhooks=False,
        supports_repository_tree=True,
        supports_files=True,
        supports_issues=False,
        supports_pull_requests=False,
        supports_comments=False,
        supports_releases=False,
        supports_permissions=False,
        object_types=("github.repository", "github.file"),
    )
    with pytest.raises(AttributeError):
        caps.supports_full_sync = False  # type: ignore[misc]


def test_manifest_frozen() -> None:
    caps = ConnectorCapabilities(
        supports_full_sync=True,
        supports_incremental_sync=False,
        supports_webhooks=False,
        supports_repository_tree=True,
        supports_files=True,
        supports_issues=False,
        supports_pull_requests=False,
        supports_comments=False,
        supports_releases=False,
        supports_permissions=False,
        object_types=("github.file",),
    )
    m = ConnectorManifest(
        connector_id="github",
        display_name="GitHub",
        version="0.1.0",
        capabilities=caps,
    )
    assert m.connector_id == "github"
    with pytest.raises(AttributeError):
        m.connector_id = "other"  # type: ignore[misc]


def _make_caps(**overrides: object) -> ConnectorCapabilities:
    defaults = dict(
        supports_full_sync=False,
        supports_incremental_sync=False,
        supports_webhooks=False,
        supports_repository_tree=False,
        supports_files=False,
        supports_issues=False,
        supports_pull_requests=False,
        supports_comments=False,
        supports_releases=False,
        supports_permissions=False,
        object_types=(),
    )
    defaults.update(overrides)
    return ConnectorCapabilities(**defaults)  # type: ignore[arg-type]


class _StubConnector(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="stub",
            display_name="Stub",
            version="0.0.1",
            capabilities=_make_caps(),
        )


def test_registry_register_and_get() -> None:
    reg = ConnectorRegistry()
    stub = _StubConnector()
    reg.register(stub)
    assert reg.get("stub") is stub


def test_registry_has() -> None:
    reg = ConnectorRegistry()
    assert not reg.has("stub")
    reg.register(_StubConnector())
    assert reg.has("stub")


def test_registry_list() -> None:
    reg = ConnectorRegistry()
    reg.register(_StubConnector())
    manifests = reg.list()
    assert len(manifests) == 1
    assert manifests[0].connector_id == "stub"


def test_registry_get_unknown_raises() -> None:
    reg = ConnectorRegistry()
    with pytest.raises(ConnectorNotFoundError):
        reg.get("missing")


def test_base_connector_unsupported_capabilities() -> None:
    stub = _StubConnector()
    with pytest.raises(UnsupportedCapabilityError):
        asyncio.run(stub.full_sync(None))  # type: ignore[arg-type]
