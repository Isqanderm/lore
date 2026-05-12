from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository


async def _seed_connection_and_repo(session: AsyncSession) -> ExternalRepositoryORM:
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
    return repo


@pytest.mark.integration
async def test_get_latest_succeeded_returns_none_when_no_runs(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_connection_and_repo(db_session)
    sync_repo = RepositorySyncRunRepository(db_session)

    result = await sync_repo.get_latest_succeeded_by_repository(repo.id)

    assert result is None


@pytest.mark.integration
async def test_get_latest_succeeded_returns_most_recent_succeeded(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_connection_and_repo(db_session)
    sync_repo = RepositorySyncRunRepository(db_session)

    now = datetime.now(UTC)
    older_run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="succeeded",
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=1, minutes=30),
        created_at=now,
        updated_at=now,
    )
    newer_run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="succeeded",
        started_at=now - timedelta(hours=1),
        finished_at=now - timedelta(minutes=30),
        created_at=now,
        updated_at=now,
    )
    failed_run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="failed",
        started_at=now - timedelta(minutes=10),
        finished_at=now - timedelta(minutes=5),
        created_at=now,
        updated_at=now,
    )
    db_session.add(older_run)
    db_session.add(newer_run)
    db_session.add(failed_run)
    await db_session.flush()

    result = await sync_repo.get_latest_succeeded_by_repository(repo.id)

    assert result is not None
    assert result.id == newer_run.id


@pytest.mark.integration
async def test_get_latest_succeeded_ignores_partial_and_running(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_connection_and_repo(db_session)
    sync_repo = RepositorySyncRunRepository(db_session)

    now = datetime.now(UTC)
    partial_run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="partial",
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    running_run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="running",
        started_at=now - timedelta(minutes=10),
        finished_at=None,
        created_at=now,
        updated_at=now,
    )
    failed_run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="failed",
        started_at=now - timedelta(minutes=30),
        finished_at=now - timedelta(minutes=20),
        created_at=now,
        updated_at=now,
    )
    db_session.add(partial_run)
    db_session.add(running_run)
    db_session.add(failed_run)
    await db_session.flush()

    result = await sync_repo.get_latest_succeeded_by_repository(repo.id)

    assert result is None
