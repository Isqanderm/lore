from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.source import SourceORM

pytestmark = pytest.mark.e2e


async def _seed_repo(session: AsyncSession) -> ExternalRepositoryORM:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:8]
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
        owner=f"e2eorg-{suffix}",
        name=f"e2erepo-{suffix}",
        full_name=f"e2eorg-{suffix}/e2erepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/e2eorg-{suffix}/e2erepo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(repo)
    await session.flush()
    return repo


async def _seed_active_doc_with_version(
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    path: str,
    content: str,
) -> tuple[DocumentORM, DocumentVersionORM]:
    now = datetime.now(UTC)
    eo = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=repo.connection_id,
        provider="github",
        object_type="github.file",
        external_id=f"{repo.full_name}:file:{path}:{uuid4().hex[:6]}",
        raw_payload_json={},
        raw_payload_hash="hash-" + uuid4().hex[:8],
        fetched_at=now,
        metadata_={},
    )
    session.add(eo)
    await session.flush()

    src = SourceORM(
        id=uuid4(),
        source_type_raw="github.file",
        source_type_canonical="github.file",
        origin=f"https://github.com/{repo.full_name}/blob/main/{path}",
        external_object_id=eo.id,
        created_at=now,
        updated_at=now,
    )
    session.add(src)
    await session.flush()

    doc = DocumentORM(
        id=uuid4(),
        source_id=src.id,
        title=path,
        path=path,
        is_active=True,
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(doc)
    await session.flush()

    dv = DocumentVersionORM(
        id=uuid4(),
        document_id=doc.id,
        version=1,
        content=content,
        checksum=hashlib.sha256(content.encode()).hexdigest(),
        created_at=now,
        metadata_={},
    )
    session.add(dv)
    await session.flush()
    return doc, dv


async def test_search_repository_returns_422_for_empty_query(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": ""},
    )
    assert response.status_code == 422


async def test_search_repository_returns_422_for_whitespace_query(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": "   "},
    )
    assert response.status_code == 422


async def test_search_repository_returns_200_with_empty_results_when_no_match(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": "zzzyyyxxx_nomatch_e2e"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "zzzyyyxxx_nomatch_e2e"
    assert data["results"] == []


async def test_search_repository_returns_404_for_unknown_repository(
    app_client_with_db: httpx.AsyncClient,
) -> None:
    unknown_id = uuid4()
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{unknown_id}/search",
        json={"query": "anything"},
    )
    assert response.status_code == 404


async def test_search_repository_happy_path(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    doc, dv = await _seed_active_doc_with_version(
        db_session,
        repo,
        "lore/sync/service.py",
        "this module handles sync lifecycle management",
    )

    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": "sync lifecycle"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["query"] == "sync lifecycle"
    assert len(data["results"]) >= 1

    first = data["results"][0]
    assert first["path"] == "lore/sync/service.py"
    assert first["document_id"] == str(doc.id)
    assert first["version_id"] == str(dv.id)
    assert isinstance(first["snippet"], str)
    assert len(first["snippet"]) > 0
    assert isinstance(first["score"], float)
    assert 0.0 < first["score"] <= 1.0
