# tests/integration/connectors/test_import_api.py
"""POST /api/v1/repositories/import with a fake connector — integration level (needs DB)."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.models.source import SourceORM


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


# ---------------------------------------------------------------------------
# Suffixed fake connectors — each test uses a unique owner/repo name so data
# committed to the shared DB does not collide across test runs.
# ---------------------------------------------------------------------------


class _FakeConnectorSuffixed(BaseConnector):
    """Fake connector that uses unique owner/repo names per suffix."""

    def __init__(self, suffix: str, *, warnings: list[str] | None = None) -> None:
        self._suffix = suffix
        self._warnings = warnings or []

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="fake",
            display_name="Fake Suffixed",
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
            owner=f"acme-{self._suffix}",
            name=f"repo-{self._suffix}",
            full_name=f"acme-{self._suffix}/repo-{self._suffix}",
            default_branch="main",
            html_url=f"https://example.com/acme-{self._suffix}/repo-{self._suffix}",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        content = "# Hello"
        path = "README.md"
        payload = {
            "path": path,
            "owner": f"acme-{self._suffix}",
            "repo": f"repo-{self._suffix}",
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw = RawExternalObject(
            provider="fake",
            object_type="github.file",
            external_id=f"acme-{self._suffix}/repo-{self._suffix}:file:{path}",
            external_url=(
                f"https://example.com/acme-{self._suffix}/repo-{self._suffix}/blob/abc/{path}"
            ),
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
                "path": path,
                "owner": f"acme-{self._suffix}",
                "repo": f"repo-{self._suffix}",
                "branch": "main",
            },
        )
        return SyncResult(connector_id="fake", raw_objects=[raw], warnings=self._warnings)

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


class _FailingFakeConnectorSuffixed(BaseConnector):
    """Fails in full_sync() — not inspect_resource() — so sync run is created before failure."""

    def __init__(self, suffix: str) -> None:
        self._suffix = suffix

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="fake",
            display_name="Failing Fake",
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
            owner=f"acme-{self._suffix}",
            name=f"repo-{self._suffix}",
            full_name=f"acme-{self._suffix}/repo-{self._suffix}",
            default_branch="main",
            html_url=f"https://example.com/acme-{self._suffix}/repo-{self._suffix}",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raise RuntimeError("simulated network failure")

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


# ---------------------------------------------------------------------------
# Test A — sync run has import trigger/mode/status
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_import_creates_sync_run_with_import_trigger(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = _FakeConnectorSuffixed(suffix)
    registry = ConnectorRegistry()
    registry.register(connector)
    app_with_db.state.connector_registry = registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={
            "url": f"https://example.com/acme-{suffix}/repo-{suffix}",
            "connector_id": "fake",
        },
    )
    assert response.status_code == 200
    data = response.json()
    repo_id = UUID(data["repository_id"])
    sync_run_id = UUID(data["sync_run_id"])

    db_session.expire_all()
    result = await db_session.execute(
        select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == sync_run_id)
    )
    run = result.scalar_one()
    assert run.repository_id == repo_id
    assert run.trigger == "import"
    assert run.mode == "full"
    assert run.status == "succeeded"


# ---------------------------------------------------------------------------
# Test B — documents have first_seen/last_seen sync run tracking
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_imported_documents_have_sync_tracking(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = _FakeConnectorSuffixed(suffix)
    registry = ConnectorRegistry()
    registry.register(connector)
    app_with_db.state.connector_registry = registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={
            "url": f"https://example.com/acme-{suffix}/repo-{suffix}",
            "connector_id": "fake",
        },
    )
    assert response.status_code == 200
    data = response.json()
    repo_id = UUID(data["repository_id"])
    sync_run_id = UUID(data["sync_run_id"])

    db_session.expire_all()
    result = await db_session.execute(
        select(DocumentORM)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == repo_id)
    )
    docs = result.scalars().all()
    assert len(docs) >= 1
    for doc in docs:
        assert doc.first_seen_sync_run_id == sync_run_id
        assert doc.last_seen_sync_run_id == sync_run_id


# ---------------------------------------------------------------------------
# Test C — brief can be generated after a successful import
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_brief_can_be_generated_after_successful_import(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    connector = _FakeConnectorSuffixed(suffix)
    registry = ConnectorRegistry()
    registry.register(connector)
    app_with_db.state.connector_registry = registry

    import_resp = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={
            "url": f"https://example.com/acme-{suffix}/repo-{suffix}",
            "connector_id": "fake",
        },
    )
    assert import_resp.status_code == 200
    repo_id = import_resp.json()["repository_id"]

    brief_resp = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/brief/generate")
    assert brief_resp.status_code == 200
    brief_data = brief_resp.json()
    assert brief_data["exists"] is True
    assert brief_data["brief"]["stats"]["total_files"] > 0


# ---------------------------------------------------------------------------
# Test D — warnings from connector produce status=partial
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_partial_import_creates_partial_sync_run(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = _FakeConnectorSuffixed(suffix, warnings=["rate limit — some files skipped"])
    registry = ConnectorRegistry()
    registry.register(connector)
    app_with_db.state.connector_registry = registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={
            "url": f"https://example.com/acme-{suffix}/repo-{suffix}",
            "connector_id": "fake",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    sync_run_id = UUID(data["sync_run_id"])

    db_session.expire_all()
    result = await db_session.execute(
        select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == sync_run_id)
    )
    run = result.scalar_one()
    assert run.status == "partial"
    assert run.trigger == "import"


# ---------------------------------------------------------------------------
# Test E — failing connector produces HTTP 500 but persists a failed sync run
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_failed_import_persists_failed_sync_run(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    full_name = f"acme-{suffix}/repo-{suffix}"
    connector = _FailingFakeConnectorSuffixed(suffix)
    registry = ConnectorRegistry()
    registry.register(connector)
    app_with_db.state.connector_registry = registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": f"https://example.com/{full_name}", "connector_id": "fake"},
    )
    assert response.status_code == 500

    # Find the repo by full_name (not from response body — it's a 500)
    db_session.expire_all()
    repo_result = await db_session.execute(
        select(ExternalRepositoryORM).where(ExternalRepositoryORM.full_name == full_name)
    )
    repo = repo_result.scalar_one()

    run_result = await db_session.execute(
        select(RepositorySyncRunORM)
        .where(RepositorySyncRunORM.repository_id == repo.id)
        .where(RepositorySyncRunORM.trigger == "import")
    )
    run = run_result.scalar_one()
    assert run.status == "failed"
    assert run.trigger == "import"


# ---------------------------------------------------------------------------
# Test F — provenance metadata is stored in document versions
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_import_provenance_in_document_version(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = _FakeConnectorSuffixed(suffix)
    registry = ConnectorRegistry()
    registry.register(connector)
    app_with_db.state.connector_registry = registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={
            "url": f"https://example.com/acme-{suffix}/repo-{suffix}",
            "connector_id": "fake",
        },
    )
    assert response.status_code == 200
    repo_id = UUID(response.json()["repository_id"])

    db_session.expire_all()
    result = await db_session.execute(
        select(DocumentVersionORM)
        .join(DocumentORM, DocumentVersionORM.document_id == DocumentORM.id)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == repo_id)
    )
    versions = result.scalars().all()
    assert len(versions) >= 1
    for v in versions:
        assert "external_id" in v.metadata_
        assert "raw_payload_hash" in v.metadata_
        assert "commit_sha" in v.metadata_
