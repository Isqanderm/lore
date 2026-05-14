from __future__ import annotations

import dataclasses
from datetime import datetime  # noqa: TCH003
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID  # noqa: TCH003

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lore.artifacts.repository_brief_service import (
    RepositoryBriefService,
    RepositoryBriefServiceResult,
)
from lore.artifacts.repository_structure_service import (
    RepositoryStructureService,
    RepositoryStructureServiceResult,
)
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.infrastructure.db.session import get_session
from lore.schema.repository_artifact import (
    ARTIFACT_TYPE_REPOSITORY_BRIEF,
    ARTIFACT_TYPE_REPOSITORY_STRUCTURE,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["repository-artifacts"])

SessionDep = Annotated["AsyncSession", Depends(get_session)]


class RepositoryBriefMissingResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_BRIEF
    exists: bool = False
    state: Literal["missing"] = "missing"
    reason: str = "brief_not_generated"


class RepositoryBriefPresentResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_BRIEF
    exists: bool = True
    state: Literal["fresh", "stale"]
    is_stale: bool
    generated_at: datetime
    source_sync_run_id: UUID
    current_sync_run_id: UUID | None
    brief: dict[str, Any]


def _build_brief_service(session: AsyncSession) -> RepositoryBriefService:
    return RepositoryBriefService(
        external_repository_repo=ExternalRepositoryRepository(session),
        sync_run_repo=RepositorySyncRunRepository(session),
        document_repo=DocumentRepository(session),
        artifact_repo=RepositoryArtifactRepository(session),
    )


def _to_response(
    result: RepositoryBriefServiceResult,
) -> RepositoryBriefMissingResponse | RepositoryBriefPresentResponse:
    if not result.exists:
        assert result.state == "missing"
        return RepositoryBriefMissingResponse(
            repository_id=result.repository_id,
            reason=result.reason or "brief_not_generated",
        )
    assert result.state in ("fresh", "stale")
    assert result.generated_at is not None
    assert result.source_sync_run_id is not None
    assert result.content is not None
    return RepositoryBriefPresentResponse(
        repository_id=result.repository_id,
        state=result.state,
        is_stale=result.is_stale,
        generated_at=result.generated_at,
        source_sync_run_id=result.source_sync_run_id,
        current_sync_run_id=result.current_sync_run_id,
        brief=dataclasses.asdict(result.content),
    )


@router.get("/repositories/{repository_id}/brief")
async def get_repository_brief(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryBriefMissingResponse | RepositoryBriefPresentResponse:
    brief_service = _build_brief_service(session)
    result = await brief_service.get_brief(repository_id)
    return _to_response(result)


@router.post("/repositories/{repository_id}/brief/generate")
async def generate_repository_brief(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryBriefPresentResponse:
    brief_service = _build_brief_service(session)
    result = await brief_service.generate_brief(repository_id)
    await session.commit()
    return _to_response(result)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Structure — new endpoints
# ---------------------------------------------------------------------------


class RepositoryStructureMissingResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    exists: bool = False
    state: Literal["missing"] = "missing"
    reason: str = "structure_not_generated"


class RepositoryStructurePresentResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    exists: bool = True
    state: Literal["fresh", "stale"]
    is_stale: bool
    generated_at: datetime
    source_sync_run_id: UUID
    current_sync_run_id: UUID | None
    structure: dict[str, Any]


def _build_structure_service(session: AsyncSession) -> RepositoryStructureService:
    return RepositoryStructureService(
        external_repository_repo=ExternalRepositoryRepository(session),
        sync_run_repo=RepositorySyncRunRepository(session),
        document_repo=DocumentRepository(session),
        artifact_repo=RepositoryArtifactRepository(session),
    )


def _structure_to_response(
    result: RepositoryStructureServiceResult,
) -> RepositoryStructureMissingResponse | RepositoryStructurePresentResponse:
    if not result.exists:
        assert result.state == "missing"
        return RepositoryStructureMissingResponse(
            repository_id=result.repository_id,
            reason=result.reason or "structure_not_generated",
        )
    assert result.state in ("fresh", "stale")
    assert result.generated_at is not None
    assert result.source_sync_run_id is not None
    assert result.content is not None
    return RepositoryStructurePresentResponse(
        repository_id=result.repository_id,
        state=result.state,
        is_stale=result.is_stale,
        generated_at=result.generated_at,
        source_sync_run_id=result.source_sync_run_id,
        current_sync_run_id=result.current_sync_run_id,
        structure=dataclasses.asdict(result.content),
    )


@router.get("/repositories/{repository_id}/structure")
async def get_repository_structure(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryStructureMissingResponse | RepositoryStructurePresentResponse:
    svc = _build_structure_service(session)
    result = await svc.get_structure(repository_id)
    return _structure_to_response(result)


@router.post("/repositories/{repository_id}/structure/generate")
async def generate_repository_structure(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryStructurePresentResponse:
    svc = _build_structure_service(session)
    result = await svc.generate_structure(repository_id)
    await session.commit()
    return _structure_to_response(result)  # type: ignore[return-value]
