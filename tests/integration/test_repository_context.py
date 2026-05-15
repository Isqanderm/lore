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
        owner=f"ctxorg-{suffix}",
        name=f"ctxrepo-{suffix}",
        full_name=f"ctxorg-{suffix}/ctxrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/ctxorg-{suffix}/ctxrepo-{suffix}",
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


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_context_respects_max_chars(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    content = "sync lifecycle management " * 100  # ~2500 chars
    for i in range(5):
        doc = await _seed_file_doc(db_session, repo, f"budget_ctx_{i}.py", is_active=True)
        await _seed_version(db_session, doc, 1, content)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=800,
        excerpt_chars=400,
    )
    assert result.used_chars <= 800
    assert result.used_chars == sum(len(s.excerpt) for s in result.sources)


async def test_context_respects_excerpt_chars_per_source(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    content = "sync lifecycle management " * 200  # ~5000 chars
    for i in range(3):
        doc = await _seed_file_doc(db_session, repo, f"excerpt_limit_ctx_{i}.py", is_active=True)
        await _seed_version(db_session, doc, 1, content)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=3,
        max_chars=5000,
        excerpt_chars=500,
    )
    assert len(result.sources) > 0
    for source in result.sources:
        assert len(source.excerpt) <= 500


async def test_context_preserves_ranking_order(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)

    # Strong: phrase in path + many content hits → score = 1.0
    strong = await _seed_file_doc(
        db_session, repo, "sync-lifecycle/rank_manager.py", is_active=True
    )
    await _seed_version(db_session, strong, 1, "sync lifecycle " * 20)

    # Weak: one content hit only → score < 1.0
    weak = await _seed_file_doc(db_session, repo, "rank_utils.py", is_active=True)
    await _seed_version(db_session, weak, 1, "sync lifecycle mentioned once")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=10,
        max_chars=10000,
        excerpt_chars=2000,
    )
    assert len(result.sources) >= 2
    paths = [s.path for s in result.sources]
    assert paths.index("sync-lifecycle/rank_manager.py") < paths.index("rank_utils.py")


async def test_context_skips_inactive_documents(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)

    active = await _seed_file_doc(db_session, repo, "active_ctx_doc.py", is_active=True)
    await _seed_version(db_session, active, 1, "sync lifecycle active content")

    inactive = await _seed_file_doc(db_session, repo, "inactive_ctx_doc.py", is_active=False)
    await _seed_version(db_session, inactive, 1, "sync lifecycle " * 20)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=10,
        max_chars=10000,
        excerpt_chars=1000,
    )
    paths = [s.path for s in result.sources]
    assert "active_ctx_doc.py" in paths
    assert "inactive_ctx_doc.py" not in paths


async def test_context_uses_latest_version_only(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "versioned_ctx_doc.py", is_active=True)
    await _seed_version(db_session, doc, 1, "old content no keyword match here")
    latest_dv = await _seed_version(db_session, doc, 2, "sync lifecycle latest content here")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=1000,
    )
    matched = [s for s in result.sources if s.path == "versioned_ctx_doc.py"]
    assert len(matched) == 1
    assert matched[0].version_id == latest_dv.id


async def test_context_includes_all_fields(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "all_fields_ctx.py", is_active=True)
    dv = await _seed_version(db_session, doc, 1, "sync lifecycle content here for fields test")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=1000,
    )
    assert len(result.sources) == 1
    source = result.sources[0]
    assert source.path == "all_fields_ctx.py"
    assert source.document_id == doc.id
    assert source.version_id == dv.id
    assert 0.0 < source.score <= 1.0
    assert isinstance(source.excerpt, str)
    assert len(source.excerpt) > 0
    assert isinstance(source.excerpt_start, int)
    assert isinstance(source.excerpt_end, int)


async def test_context_returns_empty_sources_when_no_match(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "nomatch_ctx.py", is_active=True)
    await _seed_version(db_session, doc, 1, "hello world unrelated content here")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="zzzyyyxxx_nomatch_context",
        limit=5,
        max_chars=5000,
        excerpt_chars=1000,
    )
    assert result.sources == []
    assert result.used_chars == 0


async def test_context_used_chars_matches_sum_of_excerpts(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    for i in range(3):
        doc = await _seed_file_doc(db_session, repo, f"sum_check_ctx_{i}.py", is_active=True)
        await _seed_version(db_session, doc, 1, f"sync lifecycle component {i} " * 20)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=500,
    )
    assert result.used_chars == sum(len(s.excerpt) for s in result.sources)


async def test_context_offset_invariant_in_service_output(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    content = "prefix content here " * 20 + "sync lifecycle management " * 10 + " suffix text " * 20
    doc = await _seed_file_doc(db_session, repo, "offset_check_ctx.py", is_active=True)
    await _seed_version(db_session, doc, 1, content)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=500,
    )
    assert len(result.sources) >= 1
    source = next(s for s in result.sources if s.path == "offset_check_ctx.py")
    assert content[source.excerpt_start : source.excerpt_end] == source.excerpt
