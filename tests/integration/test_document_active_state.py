# tests/integration/test_document_active_state.py
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
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import DocumentRepository

pytestmark = pytest.mark.integration


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _seed_conn_and_repo(session: AsyncSession) -> ExternalRepositoryORM:
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
        full_name=f"testorg/testrepo-{uuid4().hex[:6]}",
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
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    status: str = "succeeded",
) -> RepositorySyncRunORM:
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
        warnings=[],
        metadata_={},
    )
    session.add(run)
    await session.flush()
    return run


async def _seed_ext_object(
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    object_type: str,
    external_id: str,
) -> ExternalObjectORM:
    now = datetime.now(UTC)
    eo = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=repo.connection_id,
        provider="github",
        object_type=object_type,
        external_id=external_id,
        raw_payload_json={},
        raw_payload_hash="abc",
        fetched_at=now,
        metadata_={},
    )
    session.add(eo)
    await session.flush()
    return eo


async def _seed_source(session: AsyncSession, eo: ExternalObjectORM) -> SourceORM:
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
    is_active: bool = True,
    deleted_at: datetime | None = None,
    first_seen_sync_run_id: object | None = None,
    last_seen_sync_run_id: object | None = None,
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
        is_active=is_active,
        deleted_at=deleted_at,
        first_seen_sync_run_id=first_seen_sync_run_id,
        last_seen_sync_run_id=last_seen_sync_run_id,
    )
    session.add(doc)
    await session.flush()
    return doc


# ── A: active github.file appears in results ─────────────────────────────────


async def test_a_active_file_is_returned(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:README.md")
    src = await _seed_source(db_session, eo)
    await _seed_document(db_session, src, "README.md", is_active=True)

    result = await DocumentRepository(db_session).get_active_document_paths_by_repository_id(
        repo.id
    )

    assert "README.md" in result


# ── B: inactive github.file is excluded ──────────────────────────────────────


async def test_b_inactive_file_is_excluded(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:old.py")
    src = await _seed_source(db_session, eo)
    await _seed_document(
        db_session,
        src,
        "old.py",
        is_active=False,
        deleted_at=datetime.now(UTC),
    )

    result = await DocumentRepository(db_session).get_active_document_paths_by_repository_id(
        repo.id
    )

    assert "old.py" not in result


# ── C: non-github.file objects are excluded ──────────────────────────────────


async def test_c_non_file_object_type_excluded(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    eo = await _seed_ext_object(db_session, repo, "github.repository", "repo:testorg/testrepo")
    src = await _seed_source(db_session, eo)
    await _seed_document(db_session, src, "repo_root", is_active=True)

    result = await DocumentRepository(db_session).get_active_document_paths_by_repository_id(
        repo.id
    )

    assert "repo_root" not in result


# ── D: mark_seen_in_sync activates inactive doc, sets both sync IDs ───────────


async def test_d_mark_seen_in_sync_activates_doc(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    run = await _seed_sync_run(db_session, repo)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:lib.py")
    src = await _seed_source(db_session, eo)
    doc = await _seed_document(
        db_session,
        src,
        "lib.py",
        is_active=False,
        deleted_at=datetime.now(UTC),
        first_seen_sync_run_id=None,
    )

    await DocumentRepository(db_session).mark_seen_in_sync(doc.id, run.id)
    await db_session.flush()

    await db_session.refresh(doc)
    assert doc.is_active is True
    assert doc.deleted_at is None
    assert doc.last_seen_sync_run_id == run.id
    assert doc.first_seen_sync_run_id == run.id  # was NULL → set via COALESCE


# ── E: mark_seen_in_sync preserves existing first_seen_sync_run_id ────────────


async def test_e_mark_seen_in_sync_preserves_first_seen(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    old_run = await _seed_sync_run(db_session, repo)
    new_run = await _seed_sync_run(db_session, repo)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:main.py")
    src = await _seed_source(db_session, eo)
    doc = await _seed_document(
        db_session,
        src,
        "main.py",
        is_active=True,
        first_seen_sync_run_id=old_run.id,
        last_seen_sync_run_id=old_run.id,
    )

    await DocumentRepository(db_session).mark_seen_in_sync(doc.id, new_run.id)
    await db_session.flush()

    await db_session.refresh(doc)
    assert doc.first_seen_sync_run_id == old_run.id  # unchanged
    assert doc.last_seen_sync_run_id == new_run.id  # updated


# ── F: NULL last_seen is treated as "not seen in current sync" ────────────────


async def test_f_mark_missing_handles_null_last_seen(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    current_run = await _seed_sync_run(db_session, repo)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:stale.py")
    src = await _seed_source(db_session, eo)
    doc = await _seed_document(
        db_session,
        src,
        "stale.py",
        is_active=True,
        last_seen_sync_run_id=None,  # pre-tracking document
    )

    count = await DocumentRepository(db_session).mark_missing_github_files_inactive(
        repository_id=repo.id, sync_run_id=current_run.id
    )
    await db_session.flush()

    await db_session.refresh(doc)
    assert count >= 1
    assert doc.is_active is False
    assert doc.deleted_at is not None


# ── F2: already inactive doc is NOT re-stamped with new deleted_at ────────────


async def test_f2_already_inactive_doc_not_updated(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    current_run = await _seed_sync_run(db_session, repo)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:already_gone.py")
    src = await _seed_source(db_session, eo)
    original_deleted_at = datetime(2024, 1, 1, tzinfo=UTC)
    doc = await _seed_document(
        db_session,
        src,
        "already_gone.py",
        is_active=False,
        deleted_at=original_deleted_at,
        last_seen_sync_run_id=None,
    )

    await DocumentRepository(db_session).mark_missing_github_files_inactive(
        repository_id=repo.id, sync_run_id=current_run.id
    )
    await db_session.flush()

    await db_session.refresh(doc)
    # deleted_at must remain the original timestamp — not overwritten
    assert doc.deleted_at is not None
    # SQLAlchemy may return timezone-aware vs naive; compare just the date part
    assert doc.deleted_at.date() == original_deleted_at.date()
    assert doc.is_active is False
