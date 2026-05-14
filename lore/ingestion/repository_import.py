from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lore.ingestion.models import IngestionReport

if TYPE_CHECKING:
    from uuid import UUID

    from lore.connector_sdk.registry import ConnectorRegistry
    from lore.infrastructure.db.repositories.external_connection import (
        ExternalConnectionRepository,
    )
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.sync.service import RepositorySyncService


@dataclass
class ImportResult:
    repository_id: UUID
    connector_id: str
    status: str
    report: IngestionReport
    sync_run_id: UUID


class RepositoryImportService:
    """Orchestrates repository discovery, then delegates initial sync to RepositorySyncService."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        ext_connection_repo: ExternalConnectionRepository,
        ext_repository_repo: ExternalRepositoryRepository,
        sync_service: RepositorySyncService,
    ) -> None:
        self._registry = registry
        self._ext_connection_repo = ext_connection_repo
        self._ext_repository_repo = ext_repository_repo
        self._sync_service = sync_service

    async def import_repository(
        self,
        resource_uri: str,
        connector_id: str,
    ) -> ImportResult:
        connector = self._registry.get(connector_id)  # raises ConnectorNotFoundError if missing

        connection = await self._ext_connection_repo.get_or_create_env_pat(provider=connector_id)

        container_draft = await connector.inspect_resource(resource_uri)

        ext_repo = await self._ext_repository_repo.get_or_create(
            connection_id=connection.id,
            draft=container_draft,
        )

        sync_result = await self._sync_service.sync_repository(
            repository_id=ext_repo.id,
            trigger="import",
            mode="full",
        )

        return ImportResult(
            repository_id=ext_repo.id,
            connector_id=connector_id,
            status=sync_result.status,
            sync_run_id=sync_result.sync_run_id,
            report=IngestionReport(
                raw_objects_processed=sync_result.raw_objects_processed,
                documents_created=sync_result.documents_created,
                versions_created=sync_result.versions_created,
                versions_skipped=sync_result.versions_skipped,
                warnings=sync_result.warnings,
            ),
        )
