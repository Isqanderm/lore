"""Integration tests for DB-level idempotency of the ingestion pipeline.

Verifies that running the same import twice does not create duplicate
DocumentVersion records.
"""

from __future__ import annotations

import dataclasses
import uuid
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
from lore.infrastructure.db.models.document import DocumentVersionORM
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
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService
from lore.sync.service import RepositorySyncService
from tests.integration.connectors.conftest import canonical_hash, content_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_STATIC_CAPABILITIES = ConnectorCapabilities(
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

_STATIC_CONTENT = "# Idempotency Test"
_STATIC_PAYLOAD: dict[str, object] = {
    "path": "README.md",
    "sha": "deadbeef",
    "size": len(_STATIC_CONTENT),
    "mode": "100644",
}


class _StaticConnector(BaseConnector):
    """Connector that always returns the same RawExternalObject for idempotency testing."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="github",
            display_name="GitHub (static/idempotency)",
            version="0.0.1",
            capabilities=_STATIC_CAPABILITIES,
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider="github",
            owner="stable",
            name="repo",
            full_name="stable/repo",
            default_branch="main",
            html_url="https://github.com/stable/repo",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        # Build a template with placeholder IDs, then override them from the request.
        # This makes it obvious that the IDs are runtime values supplied by the orchestrator.
        template = RawExternalObject(
            provider="github",
            object_type="github.file",
            external_id="stable/repo:file:README.md",
            external_url="https://github.com/stable/repo/blob/deadbeef/README.md",
            connection_id=uuid.UUID(int=0),
            repository_id=uuid.UUID(int=0),
            raw_payload=_STATIC_PAYLOAD,
            raw_payload_hash=canonical_hash(_STATIC_PAYLOAD),
            content=_STATIC_CONTENT,
            content_hash=content_hash(_STATIC_CONTENT),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={
                "commit_sha": "deadbeef",
                "path": "README.md",
                "owner": "stable",
                "repo": "repo",
                "branch": "main",
            },
        )
        raw = dataclasses.replace(
            template,
            connection_id=request.connection_id,
            repository_id=request.repository_id,
        )
        return SyncResult(connector_id="github", raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


def _build_import_service(session: AsyncSession) -> RepositoryImportService:
    registry = ConnectorRegistry()
    registry.register(_StaticConnector())

    ingestion = IngestionService(
        external_object_repo=ExternalObjectRepository(session),
        source_repo=SourceRepository(session),
        document_repo=DocumentRepository(session),
        document_version_repo=DocumentVersionRepository(session),
    )
    sync_service = RepositorySyncService(
        registry=registry,
        ingestion=ingestion,
        ext_repo_repo=ExternalRepositoryRepository(session),
        sync_run_repo=RepositorySyncRunRepository(session),
        document_repo=DocumentRepository(session),
    )
    return RepositoryImportService(
        registry=registry,
        ext_connection_repo=ExternalConnectionRepository(session),
        ext_repository_repo=ExternalRepositoryRepository(session),
        sync_service=sync_service,
    )


@pytest.mark.integration
async def test_repeated_import_no_duplicate_versions(db_session: AsyncSession) -> None:
    service = _build_import_service(db_session)

    # First import
    result1 = await service.import_repository(
        "https://github.com/stable/repo-idempotency", "github"
    )
    assert result1.status == "succeeded"
    assert result1.report.versions_created == 1

    # Second import — same content, must skip version creation
    result2 = await service.import_repository(
        "https://github.com/stable/repo-idempotency", "github"
    )
    assert result2.status == "succeeded"
    assert result2.report.versions_created == 0
    assert result2.report.versions_skipped == 1

    # Verify at DB level: only one DocumentVersion exists for this document
    stmt = select(DocumentVersionORM).where(
        DocumentVersionORM.metadata_["commit_sha"].astext == "deadbeef"
    )
    result = await db_session.execute(stmt)
    versions = result.scalars().all()
    assert len(versions) == 1
