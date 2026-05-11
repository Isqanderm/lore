"""Integration tests for full repository import flow.

Uses a fake connector backed by real PostgreSQL (testcontainers).
No real GitHub API calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

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
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
)
from lore.infrastructure.db.repositories.external_connection import (
    ExternalConnectionRepository,
)
from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
from lore.infrastructure.db.repositories.external_repository import (
    ExternalRepositoryRepository,
)
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService
from tests.integration.connectors.conftest import canonical_hash, content_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_FAKE_CAPABILITIES = ConnectorCapabilities(
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


class _FakeGitHubConnector(BaseConnector):
    """Fake connector that returns one README.md file for acme/myrepo."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="github",
            display_name="GitHub (fake)",
            version="0.0.1",
            capabilities=_FAKE_CAPABILITIES,
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider="github",
            owner="acme",
            name="myrepo",
            full_name="acme/myrepo",
            default_branch="main",
            html_url="https://github.com/acme/myrepo",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        content = "# Hello World"
        payload = {"path": "README.md", "sha": "abc123", "size": len(content), "mode": "100644"}
        raw = RawExternalObject(
            provider="github",
            object_type="github.file",
            external_id="acme/myrepo:file:README.md",
            external_url="https://github.com/acme/myrepo/blob/abc123/README.md",
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash=canonical_hash(payload),
            content=content,
            content_hash=content_hash(content),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={
                "commit_sha": "abc123",
                "path": "README.md",
                "owner": "acme",
                "repo": "myrepo",
                "branch": "main",
            },
        )
        return SyncResult(connector_id="github", raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


def _build_import_service(session: AsyncSession) -> RepositoryImportService:
    registry = ConnectorRegistry()
    registry.register(_FakeGitHubConnector())

    ingestion = IngestionService(
        external_object_repo=ExternalObjectRepository(session),
        source_repo=SourceRepository(session),
        document_repo=DocumentRepository(session),
        document_version_repo=DocumentVersionRepository(session),
    )
    return RepositoryImportService(
        registry=registry,
        ingestion=ingestion,
        ext_connection_repo=ExternalConnectionRepository(session),
        ext_repository_repo=ExternalRepositoryRepository(session),
    )


@pytest.mark.integration
async def test_full_import_creates_all_records(db_session: AsyncSession) -> None:
    service = _build_import_service(db_session)
    result = await service.import_repository("https://github.com/acme/myrepo", "github")

    assert result.status == "synced"
    assert result.report.documents_created == 1
    assert result.report.versions_created == 1


@pytest.mark.integration
async def test_full_import_creates_document_version_with_provenance(
    db_session: AsyncSession,
) -> None:
    service = _build_import_service(db_session)
    import_result = await service.import_repository(
        "https://github.com/acme/myrepo-provenance", "github"
    )

    # Query DocumentVersionORM rows scoped to this specific repository import only.
    # Chain: document_versions → documents → sources → external_objects (repository_id)
    stmt = (
        select(DocumentVersionORM)
        .join(DocumentORM, DocumentVersionORM.document_id == DocumentORM.id)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == import_result.repository_id)
    )
    result = await db_session.execute(stmt)
    versions = result.scalars().all()

    assert len(versions) == 1

    version = versions[0]
    assert version.metadata_["commit_sha"] == "abc123"
    assert "external_id" in version.metadata_
    assert "raw_payload_hash" in version.metadata_
