from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.document import DocumentORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import DocumentRepository


async def _seed_connection_and_repo(
    session: AsyncSession,
) -> ExternalRepositoryORM:
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


async def _seed_external_object(
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    object_type: str,
    external_id: str,
) -> ExternalObjectORM:
    now = datetime.now(UTC)
    conn_result = await session.get(ExternalConnectionORM, repo.connection_id)
    assert conn_result is not None
    eo = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=repo.connection_id,
        provider="github",
        object_type=object_type,
        external_id=external_id,
        raw_payload_json={},
        raw_payload_hash="abc123",
        fetched_at=now,
        metadata_={},
    )
    session.add(eo)
    await session.flush()
    return eo


async def _seed_source(
    session: AsyncSession,
    eo: ExternalObjectORM,
) -> SourceORM:
    now = datetime.now(UTC)
    src = SourceORM(
        id=uuid4(),
        source_type_raw="github.file",
        source_type_canonical="github.file",
        origin=f"github://testorg/testrepo/{eo.external_id}",
        external_object_id=eo.id,
        created_at=now,
        updated_at=now,
    )
    session.add(src)
    await session.flush()
    return src


async def _seed_document(
    session: AsyncSession,
    src: SourceORM,
    path: str,
) -> DocumentORM:
    now = datetime.now(UTC)
    doc = DocumentORM(
        id=uuid4(),
        source_id=src.id,
        title=path,
        path=path,
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest.mark.integration
async def test_get_paths_returns_empty_for_repo_without_documents(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_connection_and_repo(db_session)
    doc_repo = DocumentRepository(db_session)

    result = await doc_repo.get_document_paths_by_repository_id(repo.id)

    assert result == []


@pytest.mark.integration
async def test_get_paths_returns_distinct_sorted_paths(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_connection_and_repo(db_session)
    doc_repo = DocumentRepository(db_session)

    eo = await _seed_external_object(db_session, repo, "github.file", "file:src/main.py")
    src = await _seed_source(db_session, eo)

    await _seed_document(db_session, src, "src/z_last.py")
    await _seed_document(db_session, src, "src/a_first.py")

    result = await doc_repo.get_document_paths_by_repository_id(repo.id)

    assert result == ["src/a_first.py", "src/z_last.py"]


@pytest.mark.integration
async def test_get_paths_excludes_other_object_types(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_connection_and_repo(db_session)
    doc_repo = DocumentRepository(db_session)

    eo_pr = await _seed_external_object(db_session, repo, "github.pr", "pr:42")
    src_pr = await _seed_source(db_session, eo_pr)
    await _seed_document(db_session, src_pr, "pulls/42.md")

    result = await doc_repo.get_document_paths_by_repository_id(repo.id)

    assert "pulls/42.md" not in result
