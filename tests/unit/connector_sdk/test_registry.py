import pytest

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
