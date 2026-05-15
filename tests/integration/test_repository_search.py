from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.retrieval.service import RetrievalService

pytestmark = pytest.mark.integration


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_conn_and_repo(session: AsyncSession) -> ExternalRepositoryORM:
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
        owner=f"searchorg-{suffix}",
        name=f"searchrepo-{suffix}",
        full_name=f"searchorg-{suffix}/searchrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/searchorg-{suffix}/searchrepo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(repo)
    await session.flush()
    return repo


async def _seed_file_doc(
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    path: str,
    is_active: bool = True,
) -> DocumentORM:
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
        is_active=is_active,
        deleted_at=None if is_active else now,
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(doc)
    await session.flush()
    return doc


async def _seed_version(
    session: AsyncSession,
    doc: DocumentORM,
    version: int,
    content: str,
) -> DocumentVersionORM:
    now = datetime.now(UTC)
    dv = DocumentVersionORM(
        id=uuid4(),
        document_id=doc.id,
        version=version,
        content=content,
        checksum=hashlib.sha256(content.encode()).hexdigest(),
        created_at=now,
        metadata_={},
    )
    session.add(dv)
    await session.flush()
    return dv


# ── DocumentRepository method tests ───────────────────────────────────────────


async def test_get_active_documents_with_latest_versions_returns_active_doc(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "README.md", is_active=True)
    dv = await _seed_version(db_session, doc, 1, "hello world")

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    paths = [d.path for d, _ in pairs]
    assert "README.md" in paths
    version_ids = [v.id for _, v in pairs]
    assert dv.id in version_ids


async def test_get_active_documents_with_latest_versions_excludes_inactive_doc(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "deleted.py", is_active=False)
    await _seed_version(db_session, doc, 1, "some content")

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    paths = [d.path for d, _ in pairs]
    assert "deleted.py" not in paths


async def test_get_active_documents_with_latest_versions_skips_doc_without_versions(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    await _seed_file_doc(db_session, repo, "no-version.md", is_active=True)

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    paths = [d.path for d, _ in pairs]
    assert "no-version.md" not in paths


async def test_get_active_documents_with_latest_versions_returns_only_latest_version(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "service.py", is_active=True)
    await _seed_version(db_session, doc, 1, "old content")
    latest_dv = await _seed_version(db_session, doc, 2, "new content")

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    matched = [(d, v) for d, v in pairs if d.path == "service.py"]
    assert len(matched) == 1
    _, version = matched[0]
    assert version.id == latest_dv.id
    assert version.content == "new content"


# ── RetrievalService integration tests ───────────────────────────────────────


async def test_search_repository_excludes_inactive_documents(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)

    active_doc = await _seed_file_doc(db_session, repo, "active.py", is_active=True)
    await _seed_version(db_session, active_doc, 1, "this file handles authentication logic")

    # Inactive doc with stronger content match — must NOT appear
    inactive_doc = await _seed_file_doc(
        db_session, repo, "authentication/service.py", is_active=False
    )
    await _seed_version(db_session, inactive_doc, 1, "authentication " * 10)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=10)

    paths = [r.path for r in result.results]
    assert "active.py" in paths
    assert "authentication/service.py" not in paths


async def test_search_repository_skips_doc_when_only_old_version_matches(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "service_old_match.py", is_active=True)
    await _seed_version(db_session, doc, 1, "authentication logic here")
    await _seed_version(db_session, doc, 2, "unrelated content entirely")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=10)

    paths = [r.path for r in result.results]
    assert "service_old_match.py" not in paths


async def test_search_repository_uses_latest_document_version(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "handler_latest.py", is_active=True)
    await _seed_version(db_session, doc, 1, "unrelated old content")
    latest_dv = await _seed_version(db_session, doc, 2, "sync lifecycle management")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "sync lifecycle", limit=10)

    matched = [r for r in result.results if r.path == "handler_latest.py"]
    assert len(matched) == 1
    assert matched[0].version_id == latest_dv.id


async def test_search_repository_scoped_to_target_repository(
    db_session: AsyncSession,
) -> None:
    repo_a = await _seed_conn_and_repo(db_session)
    repo_b = await _seed_conn_and_repo(db_session)

    doc_a = await _seed_file_doc(db_session, repo_a, "auth_topic.py", is_active=True)
    await _seed_version(db_session, doc_a, 1, "authentication service")

    doc_b = await _seed_file_doc(db_session, repo_b, "auth_topic.py", is_active=True)
    await _seed_version(db_session, doc_b, 1, "authentication service")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo_a.id, "authentication", limit=10)

    doc_ids = [r.document_id for r in result.results]
    assert doc_a.id in doc_ids
    assert doc_b.id not in doc_ids


async def test_search_repository_respects_limit(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    for i in range(5):
        doc = await _seed_file_doc(db_session, repo, f"limit_test_{i}.py", is_active=True)
        await _seed_version(db_session, doc, 1, f"authentication service component {i} " * 5)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=3)

    assert len(result.results) == 3


async def test_search_repository_ranks_stronger_match_first(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)

    # Weak: term in content once
    weak_doc = await _seed_file_doc(db_session, repo, "rank_misc.py", is_active=True)
    await _seed_version(db_session, weak_doc, 1, "authentication mentioned once")

    # Strong: phrase in path + many content hits
    strong_doc = await _seed_file_doc(
        db_session, repo, "authentication/rank_service.py", is_active=True
    )
    await _seed_version(db_session, strong_doc, 1, "authentication " * 10)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=10)

    assert len(result.results) >= 2
    assert result.results[0].path == "authentication/rank_service.py"
