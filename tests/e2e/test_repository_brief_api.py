"""E2E tests for GET /repositories/{id}/brief and POST /repositories/{id}/brief/generate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from lore.infrastructure.db.models.document import DocumentORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.models.source import SourceORM

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_repo(session: AsyncSession) -> ExternalRepositoryORM:
    """Seed a connection + repository with no sync runs."""
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


async def _seed_sync_run(
    session: AsyncSession, repo: ExternalRepositoryORM, status: str = "succeeded"
) -> RepositorySyncRunORM:
    """Seed a sync run for a repository."""
    now = datetime.now(UTC)
    run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status=status,
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    return run


async def _seed_document(
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    path: str,
    object_type: str = "github.file",
) -> DocumentORM:
    """Seed an external object + source + document for a repository."""
    now = datetime.now(UTC)

    ext_obj = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=repo.connection_id,
        provider="github",
        object_type=object_type,
        external_id=f"github:{repo.full_name}:{path}",
        raw_payload_json={},
        raw_payload_hash="testhash",
        fetched_at=now,
        metadata_={},
    )
    session.add(ext_obj)
    await session.flush()

    source = SourceORM(
        id=uuid4(),
        source_type_raw="github.file",
        source_type_canonical="github.file",
        origin=f"https://github.com/{repo.full_name}/blob/main/{path}",
        created_at=now,
        updated_at=now,
        external_object_id=ext_obj.id,
    )
    session.add(source)
    await session.flush()

    doc = DocumentORM(
        id=uuid4(),
        source_id=source.id,
        title=path,
        path=path,
        created_at=now,
        updated_at=now,
        metadata_={},
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest.mark.e2e
async def test_get_brief_returns_missing_when_no_brief(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /brief on repo with no brief returns missing state."""
    repo = await _seed_repo(db_session)

    response = await app_client_with_db.get(f"/api/v1/repositories/{repo.id}/brief")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "missing"
    assert data["exists"] is False
    assert data["reason"] == "brief_not_generated"


@pytest.mark.e2e
async def test_generate_brief_returns_409_when_no_sync_run(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /brief/generate on repo with no succeeded sync run returns 409."""
    repo = await _seed_repo(db_session)

    response = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "repository_not_synced"


@pytest.mark.e2e
async def test_generate_brief_creates_brief(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /brief/generate on repo with a succeeded sync run returns 200 with fresh brief."""
    repo = await _seed_repo(db_session)
    await _seed_sync_run(db_session, repo)

    response = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "fresh"
    assert data["exists"] is True
    assert data["is_stale"] is False
    assert "brief" in data


@pytest.mark.e2e
async def test_get_brief_returns_fresh_after_generate(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """After generating, GET /brief returns fresh state."""
    repo = await _seed_repo(db_session)
    await _seed_sync_run(db_session, repo)

    await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")

    response = await app_client_with_db.get(f"/api/v1/repositories/{repo.id}/brief")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "fresh"
    assert data["is_stale"] is False
    assert data["exists"] is True


@pytest.mark.e2e
async def test_get_brief_stale_after_new_sync_run(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """After generating and seeding a new sync run, GET /brief returns stale state."""
    repo = await _seed_repo(db_session)
    await _seed_sync_run(db_session, repo)

    await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")

    # Seed a new sync run — now the brief is stale
    await _seed_sync_run(db_session, repo)

    response = await app_client_with_db.get(f"/api/v1/repositories/{repo.id}/brief")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "stale"
    assert data["is_stale"] is True


@pytest.mark.e2e
async def test_generate_brief_again_makes_fresh(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """After stale state, POST /brief/generate returns fresh state."""
    repo = await _seed_repo(db_session)
    await _seed_sync_run(db_session, repo)

    await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")

    # Seed a new sync run — now the brief is stale
    await _seed_sync_run(db_session, repo)

    response = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "fresh"
    assert data["is_stale"] is False


@pytest.mark.e2e
async def test_get_brief_unknown_repository_returns_404(
    app_client_with_db: httpx.AsyncClient,
) -> None:
    """GET /brief with a random UUID returns 404 with repository_not_found error."""
    unknown_id = uuid4()
    response = await app_client_with_db.get(f"/api/v1/repositories/{unknown_id}/brief")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "repository_not_found"


@pytest.mark.e2e
async def test_generate_brief_with_real_documents(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /brief/generate with real documents populates stats correctly."""
    repo = await _seed_repo(db_session)
    await _seed_sync_run(db_session, repo)

    # Seed a source file
    await _seed_document(db_session, repo, "src/app.py", object_type="github.file")

    response = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "fresh"
    stats = data["brief"]["stats"]
    assert stats["total_files"] == 1
    assert stats["source_files"] == 1
