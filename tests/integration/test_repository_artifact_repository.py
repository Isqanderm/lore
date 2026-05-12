from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF, RepositoryArtifact


async def _seed_repo_with_run(
    session: AsyncSession,
) -> tuple[ExternalRepositoryORM, RepositorySyncRunORM]:
    now = datetime.now(UTC)
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
        owner="testorg",
        name="testrepo",
        full_name="testorg/testrepo",
        default_branch="main",
        html_url="https://github.com/testorg/testrepo",
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
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    return repo, run


def _make_artifact(repository_id: UUID, sync_run_id: UUID) -> RepositoryArtifact:
    now = datetime.now(UTC)
    return RepositoryArtifact(
        id=uuid4(),
        repository_id=repository_id,
        artifact_type=ARTIFACT_TYPE_REPOSITORY_BRIEF,
        title="Repository Brief: testorg/testrepo",
        content_json={"schema_version": 1, "generated_by": "repository_brief_service"},
        source_sync_run_id=sync_run_id,
        generated_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.integration
async def test_upsert_creates_artifact(db_session: AsyncSession) -> None:
    repo, run = await _seed_repo_with_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    artifact = _make_artifact(repo.id, run.id)
    saved = await artifact_repo.upsert(artifact)

    assert saved.repository_id == repo.id
    assert saved.artifact_type == ARTIFACT_TYPE_REPOSITORY_BRIEF
    assert saved.source_sync_run_id == run.id
    assert saved.content_json["schema_version"] == 1


@pytest.mark.integration
async def test_upsert_updates_no_duplicate(db_session: AsyncSession) -> None:
    repo, run = await _seed_repo_with_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    first = _make_artifact(repo.id, run.id)
    await artifact_repo.upsert(first)

    run2 = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="succeeded",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(run2)
    await db_session.flush()

    second = _make_artifact(repo.id, run2.id)
    saved2 = await artifact_repo.upsert(second)

    assert saved2.source_sync_run_id == run2.id
    fetched = await artifact_repo.get_by_repository_and_type(
        repo.id, ARTIFACT_TYPE_REPOSITORY_BRIEF
    )
    assert fetched is not None
    assert fetched.source_sync_run_id == run2.id


@pytest.mark.integration
async def test_get_by_repository_and_type_returns_none_when_missing(
    db_session: AsyncSession,
) -> None:
    artifact_repo = RepositoryArtifactRepository(db_session)
    result = await artifact_repo.get_by_repository_and_type(uuid4(), ARTIFACT_TYPE_REPOSITORY_BRIEF)
    assert result is None
