from __future__ import annotations

from datetime import datetime  # noqa: TCH003
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TCH003

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from lore.connector_sdk.errors import ConnectorNotFoundError, ExternalResourceNotFoundError
from lore.infrastructure.db.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
)
from lore.infrastructure.db.repositories.external_connection import ExternalConnectionRepository
from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.infrastructure.db.session import get_session
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService
from lore.sync.errors import RepositoryNotFoundError, UnsupportedSyncModeError
from lore.sync.service import RepositorySyncService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from lore.connector_sdk.registry import ConnectorRegistry

router = APIRouter(prefix="/repositories", tags=["repositories"])

SessionDep = Annotated["AsyncSession", Depends(get_session)]


class ImportRequest(BaseModel):
    url: str
    connector_id: str = "github"


class ImportResponse(BaseModel):
    repository_id: UUID
    connector_id: str
    status: str
    sync_run_id: UUID
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    warnings: list[str] = Field(default_factory=list)


class RepositorySyncResponse(BaseModel):
    sync_run_id: UUID
    repository_id: UUID
    status: str
    trigger: str
    mode: str
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings: list[str] = Field(default_factory=list)


class RepositorySyncRunListItem(BaseModel):
    id: UUID
    repository_id: UUID
    trigger: str
    mode: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings_count: int
    error_message: str | None


def _build_import_service(
    session: AsyncSession, registry: ConnectorRegistry
) -> RepositoryImportService:
    ext_conn_repo = ExternalConnectionRepository(session)
    ext_repo_repo = ExternalRepositoryRepository(session)
    sync_service = _build_sync_service(session, registry)
    return RepositoryImportService(
        registry=registry,
        ext_connection_repo=ext_conn_repo,
        ext_repository_repo=ext_repo_repo,
        sync_service=sync_service,
    )


def _build_sync_service(
    session: AsyncSession, registry: ConnectorRegistry
) -> RepositorySyncService:
    ext_repo_repo = ExternalRepositoryRepository(session)
    ext_obj_repo = ExternalObjectRepository(session)
    source_repo = SourceRepository(session)
    doc_repo = DocumentRepository(session)
    dv_repo = DocumentVersionRepository(session)
    sync_run_repo = RepositorySyncRunRepository(session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    return RepositorySyncService(registry, ingestion, ext_repo_repo, sync_run_repo, doc_repo)


@router.post("/import", response_model=ImportResponse)
async def import_repository(
    body: ImportRequest,
    request: Request,
    session: SessionDep,
) -> ImportResponse:
    registry = request.app.state.connector_registry
    svc = _build_import_service(session, registry)

    try:
        result = await svc.import_repository(body.url, body.connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExternalResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # If sync run was created before failure, mark_failed() was flushed —
        # commit persists the failed run. May also commit connection/repo if
        # created before sync started; this is acceptable diagnostic state.
        await session.commit()
        raise HTTPException(status_code=500, detail="Import sync failed") from exc

    await session.commit()

    return ImportResponse(
        repository_id=result.repository_id,
        connector_id=result.connector_id,
        status=result.status,
        sync_run_id=result.sync_run_id,
        raw_objects_processed=result.report.raw_objects_processed,
        documents_created=result.report.documents_created,
        versions_created=result.report.versions_created,
        warnings=result.report.warnings,
    )


@router.get("/{repository_id}", response_model=dict[str, str | None])
async def get_repository(
    repository_id: UUID,
    session: SessionDep,
) -> dict[str, str | None]:
    repo_repo = ExternalRepositoryRepository(session)
    repo = await repo_repo.get_by_id(repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {
        "id": str(repo.id),
        "provider": repo.provider,
        "full_name": repo.full_name,
        "default_branch": repo.default_branch,
        "html_url": repo.html_url,
        "last_synced_at": repo.last_synced_at.isoformat() if repo.last_synced_at else None,
    }


@router.post("/{repository_id}/sync", response_model=RepositorySyncResponse)
async def sync_repository(
    repository_id: UUID,
    request: Request,
    session: SessionDep,
) -> RepositorySyncResponse:
    registry = request.app.state.connector_registry
    svc = _build_sync_service(session, registry)

    try:
        result = await svc.sync_repository(repository_id, trigger="manual", mode="full")
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnsupportedSyncModeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # mark_failed was flushed in the service — commit it so the run is persisted as failed
        await session.commit()
        raise HTTPException(status_code=500, detail="Sync failed") from exc

    await session.commit()

    return RepositorySyncResponse(
        sync_run_id=result.sync_run_id,
        repository_id=result.repository_id,
        status=result.status,
        trigger=result.trigger,
        mode=result.mode,
        raw_objects_processed=result.raw_objects_processed,
        documents_created=result.documents_created,
        versions_created=result.versions_created,
        versions_skipped=result.versions_skipped,
        warnings=result.warnings,
    )


@router.get(
    "/{repository_id}/sync-runs",
    response_model=list[RepositorySyncRunListItem],
)
async def list_sync_runs(
    repository_id: UUID,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[RepositorySyncRunListItem]:
    ext_repo_repo = ExternalRepositoryRepository(session)
    repo = await ext_repo_repo.get_by_id(repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    sync_run_repo = RepositorySyncRunRepository(session)
    runs = await sync_run_repo.list_by_repository(repository_id, limit=limit)

    return [
        RepositorySyncRunListItem(
            id=run.id,
            repository_id=run.repository_id,
            trigger=run.trigger,
            mode=run.mode,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            raw_objects_processed=run.raw_objects_processed,
            documents_created=run.documents_created,
            versions_created=run.versions_created,
            versions_skipped=run.versions_skipped,
            warnings_count=len(run.warnings),
            error_message=run.error_message,
        )
        for run in runs
    ]
