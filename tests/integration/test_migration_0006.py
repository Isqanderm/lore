"""Verify repository_artifacts check constraint allows 'repository_structure'."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.schema.repository_artifact import (
    ARTIFACT_TYPE_REPOSITORY_BRIEF,
    ARTIFACT_TYPE_REPOSITORY_STRUCTURE,
    RepositoryArtifact,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _seed_repo_and_run(
    session: AsyncSession,
) -> tuple[ExternalRepositoryORM, RepositorySyncRunORM]:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:6]

    conn = ExternalConnectionORM(
        id=uuid4(),
        provider="github",
        auth_mode="env_pat",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(conn)
    await session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(),
        connection_id=conn.id,
        provider="github",
        owner="migorg",
        name=f"migrepo-{suffix}",
        full_name=f"migorg/migrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/migorg/migrepo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(repo)
    await session.flush()

    run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="succeeded",
        started_at=now,
        finished_at=now,
        warnings=[],
        metadata_={},
    )
    session.add(run)
    await session.flush()

    return repo, run


def _make_artifact(
    repository_id: UUID, sync_run_id: UUID, artifact_type: str
) -> RepositoryArtifact:
    now = datetime.now(UTC)
    return RepositoryArtifact(
        id=uuid4(),
        repository_id=repository_id,
        artifact_type=artifact_type,
        title=f"Test: {artifact_type}",
        content_json={"schema_version": 1},
        source_sync_run_id=sync_run_id,
        generated_at=now,
        created_at=now,
        updated_at=now,
    )


async def test_m_repository_structure_artifact_type_allowed(db_session: AsyncSession) -> None:
    """repository_structure artifact must persist without constraint violation."""
    repo, run = await _seed_repo_and_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    artifact = _make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE)
    saved = await artifact_repo.upsert(artifact)

    assert saved.artifact_type == ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    fetched = await artifact_repo.get_by_repository_and_type(
        repo.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    )
    assert fetched is not None
    assert fetched.source_sync_run_id == run.id


async def test_m_repository_brief_still_allowed(db_session: AsyncSession) -> None:
    """Existing repository_brief must still be accepted after constraint expansion."""
    repo, run = await _seed_repo_and_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    artifact = _make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_BRIEF)
    saved = await artifact_repo.upsert(artifact)

    assert saved.artifact_type == ARTIFACT_TYPE_REPOSITORY_BRIEF


async def test_m_both_types_coexist_for_same_repository(db_session: AsyncSession) -> None:
    """A single repository can have both artifact types simultaneously."""
    repo, run = await _seed_repo_and_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    await artifact_repo.upsert(_make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_BRIEF))
    await artifact_repo.upsert(_make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE))

    brief = await artifact_repo.get_by_repository_and_type(repo.id, ARTIFACT_TYPE_REPOSITORY_BRIEF)
    structure = await artifact_repo.get_by_repository_and_type(
        repo.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    )
    assert brief is not None
    assert structure is not None
