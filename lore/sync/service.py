from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lore.connector_sdk.models import FullSyncRequest
from lore.sync.errors import RepositoryNotFoundError, UnsupportedSyncModeError
from lore.sync.models import RepositorySyncResult

if TYPE_CHECKING:
    from uuid import UUID

    from lore.connector_sdk.registry import ConnectorRegistry
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.infrastructure.db.repositories.repository_sync_run import (
        RepositorySyncRunRepository,
    )
    from lore.ingestion.service import IngestionService


class RepositorySyncService:
    """Provider-agnostic sync lifecycle orchestrator for existing repositories."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        ingestion: IngestionService,
        ext_repo_repo: ExternalRepositoryRepository,
        sync_run_repo: RepositorySyncRunRepository,
    ) -> None:
        self._registry = registry
        self._ingestion = ingestion
        self._ext_repo_repo = ext_repo_repo
        self._sync_run_repo = sync_run_repo

    async def sync_repository(
        self,
        repository_id: UUID,
        trigger: str = "manual",
        mode: str = "full",
    ) -> RepositorySyncResult:
        if mode != "full":
            raise UnsupportedSyncModeError(mode)

        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        # raises ConnectorNotFoundError if provider not registered
        connector = self._registry.get(repo.provider)

        run = await self._sync_run_repo.create_running(
            repository_id=repo.id,
            connector_id=repo.provider,
            trigger=trigger,
            mode=mode,
        )

        try:
            request = FullSyncRequest(
                connection_id=repo.connection_id,
                repository_id=repo.id,
                resource_uri=repo.html_url,
            )
            sync_result = await connector.full_sync(request)
            report = await self._ingestion.ingest_sync_result(sync_result, connector)

            status = "partial" if report.warnings else "succeeded"

            await self._sync_run_repo.mark_finished(
                run_id=run.id,
                status=status,
                raw_objects_processed=report.raw_objects_processed,
                documents_created=report.documents_created,
                versions_created=report.versions_created,
                versions_skipped=report.versions_skipped,
                warnings=report.warnings,
                metadata={},
            )
            await self._ext_repo_repo.mark_synced(repo.id, datetime.now(UTC))

            return RepositorySyncResult(
                sync_run_id=run.id,
                repository_id=repo.id,
                status=status,
                trigger=trigger,
                mode=mode,
                raw_objects_processed=report.raw_objects_processed,
                documents_created=report.documents_created,
                versions_created=report.versions_created,
                versions_skipped=report.versions_skipped,
                warnings=report.warnings,
            )

        except Exception as exc:
            await self._sync_run_repo.mark_failed(
                run_id=run.id,
                error_message=str(exc),
            )
            # Known limitation: the route handler commits both mark_failed and any
            # partial ingestion flushes in one transaction. This is acceptable for
            # PR #3; a future PR may isolate sync_run persistence in its own transaction.
            raise
