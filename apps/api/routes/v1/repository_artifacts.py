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
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.infrastructure.db.session import get_session
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF

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


async def _get_brief_service(
    session: SessionDep,
) -> RepositoryBriefService:
    return RepositoryBriefService(
        external_repository_repo=ExternalRepositoryRepository(session),
        sync_run_repo=RepositorySyncRunRepository(session),
        document_repo=DocumentRepository(session),
        artifact_repo=RepositoryArtifactRepository(session),
    )


BriefServiceDep = Annotated[RepositoryBriefService, Depends(_get_brief_service)]


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
    brief_service: BriefServiceDep,
) -> RepositoryBriefMissingResponse | RepositoryBriefPresentResponse:
    result = await brief_service.get_brief(repository_id)
    return _to_response(result)


@router.post("/repositories/{repository_id}/brief/generate", status_code=201)
async def generate_repository_brief(
    repository_id: UUID,
    brief_service: BriefServiceDep,
) -> RepositoryBriefPresentResponse:
    result = await brief_service.generate_brief(repository_id)
    return _to_response(result)  # type: ignore[return-value]
