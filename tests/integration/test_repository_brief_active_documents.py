"""Verify that Repository Brief counts only active documents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.artifacts.repository_brief_service import RepositoryBriefService
from lore.infrastructure.db.models.document import DocumentORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository

pytestmark = pytest.mark.integration


async def _seed_full_repo(
    session: AsyncSession,
) -> tuple[ExternalRepositoryORM, RepositorySyncRunORM]:
    """Seed connection + repo + one active doc + one inactive doc + succeeded sync run."""
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
        owner="brieforg",
        name=f"briefrepo-{suffix}",
        full_name=f"brieforg/briefrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/brieforg/briefrepo-{suffix}",
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

    # Active document — README.md
    eo_readme = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=conn.id,
        provider="github",
        object_type="github.file",
        external_id=f"brieforg/briefrepo-{suffix}:file:README.md",
        raw_payload_json={},
        raw_payload_hash="hash1",
        fetched_at=now,
        metadata_={},
    )
    session.add(eo_readme)
    await session.flush()

    src_readme = SourceORM(
        id=uuid4(),
        source_type_raw="github.file",
        source_type_canonical="github.file",
        origin="github://brieforg/briefrepo/README.md",
        external_object_id=eo_readme.id,
        created_at=now,
        updated_at=now,
    )
    session.add(src_readme)
    await session.flush()

    doc_readme = DocumentORM(
        id=uuid4(),
        source_id=src_readme.id,
        title="README.md",
        path="README.md",
        metadata_={},
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    session.add(doc_readme)
    await session.flush()

    # Inactive document — deleted.py
    eo_deleted = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=conn.id,
        provider="github",
        object_type="github.file",
        external_id=f"brieforg/briefrepo-{suffix}:file:deleted.py",
        raw_payload_json={},
        raw_payload_hash="hash2",
        fetched_at=now,
        metadata_={},
    )
    session.add(eo_deleted)
    await session.flush()

    src_deleted = SourceORM(
        id=uuid4(),
        source_type_raw="github.file",
        source_type_canonical="github.file",
        origin="github://brieforg/briefrepo/deleted.py",
        external_object_id=eo_deleted.id,
        created_at=now,
        updated_at=now,
    )
    session.add(src_deleted)
    await session.flush()

    doc_deleted = DocumentORM(
        id=uuid4(),
        source_id=src_deleted.id,
        title="deleted.py",
        path="deleted.py",
        metadata_={},
        created_at=now,
        updated_at=now,
        is_active=False,
        deleted_at=now,
    )
    session.add(doc_deleted)
    await session.flush()

    return repo, run


async def test_l_brief_excludes_inactive_documents(db_session: AsyncSession) -> None:
    repo, run = await _seed_full_repo(db_session)

    svc = RepositoryBriefService(
        external_repository_repo=ExternalRepositoryRepository(db_session),
        sync_run_repo=RepositorySyncRunRepository(db_session),
        document_repo=DocumentRepository(db_session),
        artifact_repo=RepositoryArtifactRepository(db_session),
    )

    result = await svc.generate_brief(repo.id)

    assert result.exists is True
    assert result.content is not None
    # Only README.md is active — total_files must be 1
    assert result.content.stats.total_files == 1
    # deleted.py must not appear in any path-derived list
    paths_in_important = [f.path for f in result.content.important_files]
    assert "deleted.py" not in paths_in_important
