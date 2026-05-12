from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lore.connector_sdk.models import FullSyncRequest

if TYPE_CHECKING:
    from uuid import UUID

    from lore.connector_sdk.registry import ConnectorRegistry
    from lore.infrastructure.db.repositories.external_connection import (
        ExternalConnectionRepository,
    )
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.ingestion.models import IngestionReport
    from lore.ingestion.service import IngestionService


@dataclass
class ImportResult:
    repository_id: UUID
    connector_id: str
    status: str
    report: IngestionReport


class RepositoryImportService:
    """Orchestrates: inspect_resource → full_sync → ingest. Provider-agnostic."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        ingestion: IngestionService,
        ext_connection_repo: ExternalConnectionRepository,
        ext_repository_repo: ExternalRepositoryRepository,
    ) -> None:
        self._registry = registry
        self._ingestion = ingestion
        self._ext_connection_repo = ext_connection_repo
        self._ext_repository_repo = ext_repository_repo

    async def import_repository(
        self,
        resource_uri: str,
        connector_id: str,
    ) -> ImportResult:
        connector = self._registry.get(connector_id)  # raises ConnectorNotFoundError if missing

        # 1. Get or create env-PAT connection record
        connection = await self._ext_connection_repo.get_or_create_env_pat(provider=connector_id)

        # 2. Inspect resource — provider-agnostic metadata fetch
        container_draft = await connector.inspect_resource(resource_uri)

        # 3. Get or create external repository record
        ext_repo = await self._ext_repository_repo.get_or_create(
            connection_id=connection.id,
            draft=container_draft,
        )

        # 4. Build sync request and run full sync
        request = FullSyncRequest(
            connection_id=connection.id,
            repository_id=ext_repo.id,
            resource_uri=resource_uri,
        )
        sync_result = await connector.full_sync(request)

        # 5. Ingest raw objects
        report = await self._ingestion.ingest_sync_result(sync_result, connector)

        # 6. Mark repository as synced
        await self._ext_repository_repo.mark_synced(ext_repo.id, datetime.now(UTC))

        # TODO: record sync_run with trigger="import" once RepositoryImportService
        # is refactored to delegate ingestion to RepositorySyncService.
        return ImportResult(
            repository_id=ext_repo.id,
            connector_id=connector_id,
            status="synced",
            report=report,
        )
