# tests/e2e/test_connectors_endpoint.py
"""GET /api/v1/connectors returns list of registered connectors."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.manifest import GITHUB_MANIFEST


class _StubGitHub(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return GITHUB_MANIFEST


@pytest.fixture
def github_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(_StubGitHub())
    return registry


def _get_app(client: AsyncClient) -> Any:
    """Access the underlying ASGI app from an AsyncClient regardless of httpx version."""
    transport = client._transport
    if isinstance(transport, ASGITransport):
        return transport.app
    raise RuntimeError("AsyncClient transport is not ASGITransport")


@pytest.mark.e2e
async def test_connectors_endpoint_returns_github(
    client: AsyncClient, github_registry: ConnectorRegistry
) -> None:
    _get_app(client).state.connector_registry = github_registry

    response = await client.get("/api/v1/connectors")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["connector_id"] == "github"
    assert data[0]["capabilities"]["supports_full_sync"] is True
    assert data[0]["capabilities"]["supports_webhooks"] is False


@pytest.mark.e2e
async def test_connectors_empty_registry(client: AsyncClient) -> None:
    _get_app(client).state.connector_registry = ConnectorRegistry()

    response = await client.get("/api/v1/connectors")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.e2e
async def test_webhook_endpoint_returns_501(client: AsyncClient) -> None:
    _get_app(client).state.connector_registry = ConnectorRegistry()

    response = await client.post("/api/v1/connectors/github/webhook")
    assert response.status_code == 501
