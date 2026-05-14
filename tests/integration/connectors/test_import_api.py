# tests/integration/connectors/test_import_api.py
"""POST /api/v1/repositories/import with a fake connector — integration level (needs DB)."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
)
from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.normalizer import GitHubNormalizer


class _FakeConnector(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="fake",
            display_name="Fake",
            version="0.0.1",
            capabilities=ConnectorCapabilities(
                supports_full_sync=True,
                supports_incremental_sync=False,
                supports_webhooks=False,
                supports_repository_tree=False,
                supports_files=True,
                supports_issues=False,
                supports_pull_requests=False,
                supports_comments=False,
                supports_releases=False,
                supports_permissions=False,
                object_types=("github.file",),
            ),
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider="fake",
            owner="acme",
            name="apirepo",
            full_name="acme/apirepo",
            default_branch="main",
            html_url="https://example.com/acme/apirepo",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        content = "# API Hello"
        payload = {"path": "README.md"}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw = RawExternalObject(
            provider="fake",
            object_type="github.file",
            external_id="acme/apirepo:file:README.md",
            external_url="https://example.com/acme/apirepo/blob/abc/README.md",
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
            content=content,
            content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={
                "commit_sha": "abc123",
                "path": "README.md",
                "owner": "acme",
                "repo": "apirepo",
                "branch": "main",
            },
        )
        return SyncResult(connector_id="fake", raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


@pytest.fixture
def fake_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(_FakeConnector())
    return registry


@pytest.mark.integration
async def test_import_endpoint_returns_200(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    fake_registry: ConnectorRegistry,
) -> None:
    """POST /import needs DB — run as integration test, not E2E."""
    app_with_db.state.connector_registry = fake_registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "fake"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "repository_id" in data
    assert UUID(data["repository_id"])  # valid UUID
    assert data["status"] == "succeeded"
    assert "sync_run_id" in data
    assert UUID(data["sync_run_id"])  # valid UUID
    assert data["connector_id"] == "fake"
    assert data["documents_created"] == 1
    assert data["versions_created"] == 1


@pytest.mark.integration
async def test_import_endpoint_unknown_connector_returns_404(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    fake_registry: ConnectorRegistry,
) -> None:
    app_with_db.state.connector_registry = fake_registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "unknown"},
    )
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
