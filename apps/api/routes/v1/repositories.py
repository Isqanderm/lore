from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TCH003

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from lore.connector_sdk.errors import ConnectorNotFoundError, ExternalResourceNotFoundError
from lore.infrastructure.db.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
)
from lore.infrastructure.db.repositories.external_connection import ExternalConnectionRepository
from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.infrastructure.db.session import get_session
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService

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
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    warnings: list[str] = Field(default_factory=list)


def _build_import_service(
    session: AsyncSession, registry: ConnectorRegistry
) -> RepositoryImportService:
    ext_conn_repo = ExternalConnectionRepository(session)
    ext_repo_repo = ExternalRepositoryRepository(session)
    ext_obj_repo = ExternalObjectRepository(session)
    source_repo = SourceRepository(session)
    doc_repo = DocumentRepository(session)
    dv_repo = DocumentVersionRepository(session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    return RepositoryImportService(registry, ingestion, ext_conn_repo, ext_repo_repo)


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

    await session.commit()

    return ImportResponse(
        repository_id=result.repository_id,
        connector_id=result.connector_id,
        status=result.status,
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
