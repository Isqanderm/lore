# Document Active State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track which GitHub files are currently present in a repository and make Repository Brief use only active (non-deleted) files.

**Architecture:** Soft-delete pattern — add `is_active`, `deleted_at`, `first_seen_sync_run_id`, `last_seen_sync_run_id` to `documents`. IngestionService marks each seen document via `mark_seen_in_sync`. After a fully succeeded sync, RepositorySyncService calls `mark_missing_github_files_inactive` to deactivate files not seen. Repository Brief switches to `get_active_document_paths_by_repository_id`. No physical deletes, no API contract changes.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async (ORM + Core UPDATE), Alembic, PostgreSQL 16 + pgvector, FastAPI, pytest + testcontainers

---

## File Map

| Action | Path |
|---|---|
| Create | `migrations/versions/0005_document_active_state.py` |
| Modify | `lore/infrastructure/db/models/document.py` |
| Modify | `lore/schema/document.py` |
| Modify | `lore/infrastructure/db/repositories/document.py` |
| Modify | `lore/ingestion/service.py` |
| Modify | `lore/sync/service.py` |
| Modify | `apps/api/routes/v1/repositories.py` |
| Modify | `lore/artifacts/repository_brief_service.py` |
| Modify | `tests/unit/ingestion/_fakes.py` |
| Create | `tests/unit/ingestion/test_sync_run_tracking.py` |
| Create | `tests/integration/test_document_active_state.py` |
| Create | `tests/integration/connectors/test_sync_document_lifecycle.py` |
| Create | `tests/integration/test_repository_brief_active_documents.py` |
| Create | `tests/integration/test_migration_0005.py` |

---

## Task 1: Migration — add active-state columns to `documents`

**Files:**
- Create: `migrations/versions/0005_document_active_state.py`

- [ ] **Step 1: Create migration file**

```python
# migrations/versions/0005_document_active_state.py
"""document_active_state — soft-delete and sync tracking for documents

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "first_seen_sync_run_id",
            sa.UUID(),
            sa.ForeignKey(
                "repository_sync_runs.id",
                name="fk_documents_first_seen_sync_run_id",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "last_seen_sync_run_id",
            sa.UUID(),
            sa.ForeignKey(
                "repository_sync_runs.id",
                name="fk_documents_last_seen_sync_run_id",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_is_active", "documents", ["is_active"])
    op.create_index(
        "ix_documents_first_seen_sync_run_id",
        "documents",
        ["first_seen_sync_run_id"],
    )
    op.create_index(
        "ix_documents_last_seen_sync_run_id",
        "documents",
        ["last_seen_sync_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_last_seen_sync_run_id", "documents")
    op.drop_index("ix_documents_first_seen_sync_run_id", "documents")
    op.drop_index("ix_documents_is_active", "documents")
    op.drop_column("documents", "last_seen_sync_run_id")
    op.drop_column("documents", "first_seen_sync_run_id")
    op.drop_column("documents", "deleted_at")
    op.drop_column("documents", "is_active")
```

- [ ] **Step 2: Verify migration chain is correct**

```bash
grep "down_revision" migrations/versions/0005_document_active_state.py
# Expected: down_revision = "0004"
grep "revision" migrations/versions/0004_repository_artifacts.py
# Expected: revision = "0004"
```

- [ ] **Step 3: Commit migration**

```bash
git add migrations/versions/0005_document_active_state.py
git commit -m "feat: migration 0005 — add document active state columns"
```

---

## Task 2: DocumentORM — add 4 mapped columns

**Files:**
- Modify: `lore/infrastructure/db/models/document.py`

Current file has `DocumentORM` ending at `metadata_`. Add after `updated_at`.

- [ ] **Step 1: Add 4 new fields to DocumentORM**

Replace the `DocumentORM` class body with:

```python
# lore/infrastructure/db/models/document.py
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(nullable=False)
    path: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    document_kind: Mapped[str | None] = mapped_column(nullable=True, index=True)
    logical_path: Mapped[str | None] = mapped_column(nullable=True, index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False, server_default=sa.text("true"), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_sync_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("repository_sync_runs.id"), nullable=True, index=True
    )
    last_seen_sync_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("repository_sync_runs.id"), nullable=True, index=True
    )
```

`DocumentVersionORM` below is unchanged — leave it as-is.

- [ ] **Step 2: Run mypy on the modified file**

```bash
python -m mypy lore/infrastructure/db/models/document.py --ignore-missing-imports
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add lore/infrastructure/db/models/document.py
git commit -m "feat: add is_active, deleted_at, first/last_seen_sync_run_id to DocumentORM"
```

---

## Task 3: Document schema dataclass — add 4 fields with defaults

**Files:**
- Modify: `lore/schema/document.py`

- [ ] **Step 1: Add 4 fields to Document dataclass**

```python
# lore/schema/document.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Document:
    id: UUID
    source_id: UUID
    title: str
    path: str
    created_at: datetime
    updated_at: datetime
    document_kind: str | None = None
    logical_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    deleted_at: datetime | None = None
    first_seen_sync_run_id: UUID | None = None
    last_seen_sync_run_id: UUID | None = None


@dataclass(frozen=True)
class DocumentVersion:
    id: UUID
    document_id: UUID
    version: int
    content: str
    checksum: str
    created_at: datetime
    version_ref: str | None = None
    source_updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 2: Verify existing schema tests still pass**

```bash
python -m pytest tests/unit/test_schema_document.py -v
```

Expected: all pass (new fields have defaults, frozen dataclass construction still works).

- [ ] **Step 3: Commit**

```bash
git add lore/schema/document.py
git commit -m "feat: add active-state fields to Document schema dataclass"
```

---

## Task 4: DocumentRepository — update mapping and create()

**Files:**
- Modify: `lore/infrastructure/db/repositories/document.py`

- [ ] **Step 1: Update `_doc_orm_to_schema` to map the 4 new fields**

Find the `_doc_orm_to_schema` function (currently lines 19-30). Replace it:

```python
def _doc_orm_to_schema(orm: DocumentORM) -> Document:
    return Document(
        id=orm.id,
        source_id=orm.source_id,
        title=orm.title,
        path=orm.path,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        document_kind=orm.document_kind,
        logical_path=orm.logical_path,
        metadata=orm.metadata_,
        is_active=orm.is_active,
        deleted_at=orm.deleted_at,
        first_seen_sync_run_id=orm.first_seen_sync_run_id,
        last_seen_sync_run_id=orm.last_seen_sync_run_id,
    )
```

- [ ] **Step 2: Update `create()` to persist the 4 new fields**

Find the `create` method in `DocumentRepository`. Replace the `DocumentORM(...)` constructor call:

```python
async def create(self, doc: Document) -> Document:
    orm = DocumentORM(
        id=doc.id,
        source_id=doc.source_id,
        title=doc.title,
        path=doc.path,
        document_kind=doc.document_kind,
        logical_path=doc.logical_path,
        metadata_=doc.metadata,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        is_active=doc.is_active,
        deleted_at=doc.deleted_at,
        first_seen_sync_run_id=doc.first_seen_sync_run_id,
        last_seen_sync_run_id=doc.last_seen_sync_run_id,
    )
    self.session.add(orm)
    await self.session.flush()
    return _doc_orm_to_schema(orm)
```

- [ ] **Step 3: Run existing integration tests to verify nothing is broken**

```bash
python -m pytest tests/integration/test_document_repository_paths.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add lore/infrastructure/db/repositories/document.py
git commit -m "feat: map and persist active-state fields in DocumentRepository"
```

---

## Task 5: TDD — `get_active_document_paths_by_repository_id`

**Files:**
- Create: `tests/integration/test_document_active_state.py`
- Modify: `lore/infrastructure/db/repositories/document.py`

- [ ] **Step 1: Create test file with seed helpers and tests A, B, C**

```python
# tests/integration/test_document_active_state.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import select

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
        id=uuid4(), provider="github", auth_mode="env_pat",
        metadata_={}, created_at=now, updated_at=now,
    )
    session.add(conn)
    await session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(), connection_id=conn.id, provider="github",
        owner="testorg", name="testrepo",
        full_name=f"testorg/testrepo-{uuid4().hex[:6]}",
        default_branch="main",
        html_url="https://github.com/testorg/testrepo",
        metadata_={}, created_at=now, updated_at=now,
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
        id=uuid4(), repository_id=repo.id,
        connector_id="github", trigger="manual", mode="full",
        status=status, started_at=now, finished_at=now,
        warnings=[], metadata_={},
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
        id=uuid4(), repository_id=repo.id,
        connection_id=repo.connection_id, provider="github",
        object_type=object_type, external_id=external_id,
        raw_payload_json={}, raw_payload_hash="abc",
        fetched_at=now, metadata_={},
    )
    session.add(eo)
    await session.flush()
    return eo


async def _seed_source(session: AsyncSession, eo: ExternalObjectORM) -> SourceORM:
    now = datetime.now(UTC)
    src = SourceORM(
        id=uuid4(), source_type_raw="github.file",
        source_type_canonical="github.file",
        origin=f"github://testorg/testrepo/{eo.external_id}",
        external_object_id=eo.id, created_at=now, updated_at=now,
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
    first_seen_sync_run_id=None,
    last_seen_sync_run_id=None,
) -> DocumentORM:
    now = datetime.now(UTC)
    doc = DocumentORM(
        id=uuid4(), source_id=src.id,
        title=path, path=path, metadata_={},
        created_at=now, updated_at=now,
        is_active=is_active, deleted_at=deleted_at,
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

    result = await DocumentRepository(db_session).get_active_document_paths_by_repository_id(repo.id)

    assert "README.md" in result


# ── B: inactive github.file is excluded ──────────────────────────────────────


async def test_b_inactive_file_is_excluded(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:old.py")
    src = await _seed_source(db_session, eo)
    await _seed_document(
        db_session, src, "old.py",
        is_active=False, deleted_at=datetime.now(UTC),
    )

    result = await DocumentRepository(db_session).get_active_document_paths_by_repository_id(repo.id)

    assert "old.py" not in result


# ── C: non-github.file objects are excluded ──────────────────────────────────


async def test_c_non_file_object_type_excluded(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    eo = await _seed_ext_object(db_session, repo, "github.repository", "repo:testorg/testrepo")
    src = await _seed_source(db_session, eo)
    await _seed_document(db_session, src, "repo_root", is_active=True)

    result = await DocumentRepository(db_session).get_active_document_paths_by_repository_id(repo.id)

    assert "repo_root" not in result
```

- [ ] **Step 2: Run tests A, B, C — expect FAIL (method does not exist yet)**

```bash
python -m pytest tests/integration/test_document_active_state.py::test_a_active_file_is_returned tests/integration/test_document_active_state.py::test_b_inactive_file_is_excluded tests/integration/test_document_active_state.py::test_c_non_file_object_type_excluded -v
```

Expected: `AttributeError: 'DocumentRepository' object has no attribute 'get_active_document_paths_by_repository_id'`

- [ ] **Step 3: Add `get_active_document_paths_by_repository_id` to DocumentRepository**

In `lore/infrastructure/db/repositories/document.py`, add after `get_document_paths_by_repository_id`:

```python
async def get_active_document_paths_by_repository_id(self, repository_id: UUID) -> list[str]:
    result = await self.session.execute(
        select(DocumentORM.path)
        .distinct()
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(
            ExternalObjectORM.repository_id == repository_id,
            ExternalObjectORM.object_type == _GITHUB_FILE_OBJECT_TYPE,
            DocumentORM.is_active.is_(True),
        )
        .order_by(DocumentORM.path)
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: Run tests A, B, C — expect PASS**

```bash
python -m pytest tests/integration/test_document_active_state.py::test_a_active_file_is_returned tests/integration/test_document_active_state.py::test_b_inactive_file_is_excluded tests/integration/test_document_active_state.py::test_c_non_file_object_type_excluded -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_document_active_state.py lore/infrastructure/db/repositories/document.py
git commit -m "feat: add get_active_document_paths_by_repository_id to DocumentRepository"
```

---

## Task 6: TDD — `mark_seen_in_sync`

**Files:**
- Modify: `tests/integration/test_document_active_state.py` (append tests D, E)
- Modify: `lore/infrastructure/db/repositories/document.py`

- [ ] **Step 1: Append tests D and E to test file**

```python
# append to tests/integration/test_document_active_state.py


# ── D: mark_seen_in_sync activates inactive doc, sets both sync IDs ───────────


async def test_d_mark_seen_in_sync_activates_doc(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    run = await _seed_sync_run(db_session, repo)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:lib.py")
    src = await _seed_source(db_session, eo)
    doc = await _seed_document(
        db_session, src, "lib.py",
        is_active=False, deleted_at=datetime.now(UTC),
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
        db_session, src, "main.py",
        is_active=True,
        first_seen_sync_run_id=old_run.id,
        last_seen_sync_run_id=old_run.id,
    )

    await DocumentRepository(db_session).mark_seen_in_sync(doc.id, new_run.id)
    await db_session.flush()

    await db_session.refresh(doc)
    assert doc.first_seen_sync_run_id == old_run.id  # unchanged
    assert doc.last_seen_sync_run_id == new_run.id    # updated
```

- [ ] **Step 2: Run tests D, E — expect FAIL**

```bash
python -m pytest tests/integration/test_document_active_state.py::test_d_mark_seen_in_sync_activates_doc tests/integration/test_document_active_state.py::test_e_mark_seen_in_sync_preserves_first_seen -v
```

Expected: `AttributeError: 'DocumentRepository' object has no attribute 'mark_seen_in_sync'`

- [ ] **Step 3: Add `mark_seen_in_sync` to DocumentRepository**

Add these imports at the top of `lore/infrastructure/db/repositories/document.py` (update existing `from sqlalchemy import select` line):

```python
from sqlalchemy import func, or_, select, update
```

Then add method to `DocumentRepository`:

```python
async def mark_seen_in_sync(self, document_id: UUID, sync_run_id: UUID) -> None:
    stmt = (
        update(DocumentORM)
        .where(DocumentORM.id == document_id)
        .values(
            is_active=True,
            deleted_at=None,
            first_seen_sync_run_id=func.coalesce(
                DocumentORM.first_seen_sync_run_id, sync_run_id
            ),
            last_seen_sync_run_id=sync_run_id,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    await self.session.execute(stmt)
```

- [ ] **Step 4: Run tests D, E — expect PASS**

```bash
python -m pytest tests/integration/test_document_active_state.py::test_d_mark_seen_in_sync_activates_doc tests/integration/test_document_active_state.py::test_e_mark_seen_in_sync_preserves_first_seen -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_document_active_state.py lore/infrastructure/db/repositories/document.py
git commit -m "feat: add mark_seen_in_sync to DocumentRepository"
```

---

## Task 7: TDD — `mark_missing_github_files_inactive`

**Files:**
- Modify: `tests/integration/test_document_active_state.py` (append tests F, F2)
- Modify: `lore/infrastructure/db/repositories/document.py`

- [ ] **Step 1: Append tests F and F2 to test file**

```python
# append to tests/integration/test_document_active_state.py


# ── F: NULL last_seen is treated as "not seen in current sync" ────────────────


async def test_f_mark_missing_handles_null_last_seen(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    current_run = await _seed_sync_run(db_session, repo)
    eo = await _seed_ext_object(db_session, repo, "github.file", "file:stale.py")
    src = await _seed_source(db_session, eo)
    doc = await _seed_document(
        db_session, src, "stale.py",
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
        db_session, src, "already_gone.py",
        is_active=False, deleted_at=original_deleted_at,
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
```

- [ ] **Step 2: Run tests F, F2 — expect FAIL**

```bash
python -m pytest tests/integration/test_document_active_state.py::test_f_mark_missing_handles_null_last_seen tests/integration/test_document_active_state.py::test_f2_already_inactive_doc_not_updated -v
```

Expected: `AttributeError: 'DocumentRepository' object has no attribute 'mark_missing_github_files_inactive'`

- [ ] **Step 3: Add `mark_missing_github_files_inactive` to DocumentRepository**

```python
async def mark_missing_github_files_inactive(
    self,
    repository_id: UUID,
    sync_run_id: UUID,
) -> int:
    subq = (
        select(DocumentORM.id)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(
            ExternalObjectORM.repository_id == repository_id,
            ExternalObjectORM.object_type == _GITHUB_FILE_OBJECT_TYPE,
            DocumentORM.is_active.is_(True),
            or_(
                DocumentORM.last_seen_sync_run_id.is_(None),
                DocumentORM.last_seen_sync_run_id != sync_run_id,
            ),
        )
    )
    stmt = (
        update(DocumentORM)
        .where(DocumentORM.id.in_(subq))
        .values(
            is_active=False,
            deleted_at=func.now(),
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    result = await self.session.execute(stmt)
    return result.rowcount or 0
```

- [ ] **Step 4: Run tests F, F2 — expect PASS**

```bash
python -m pytest tests/integration/test_document_active_state.py::test_f_mark_missing_handles_null_last_seen tests/integration/test_document_active_state.py::test_f2_already_inactive_doc_not_updated -v
```

Expected: 2 passed.

- [ ] **Step 5: Run all A–F2 tests together**

```bash
python -m pytest tests/integration/test_document_active_state.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_document_active_state.py lore/infrastructure/db/repositories/document.py
git commit -m "feat: add mark_missing_github_files_inactive to DocumentRepository"
```

---

## Task 8: Update FakeDocumentRepository

**Files:**
- Modify: `tests/unit/ingestion/_fakes.py`

- [ ] **Step 1: Add `seen_in_sync_calls` list and `mark_seen_in_sync` stub to FakeDocumentRepository**

In `tests/unit/ingestion/_fakes.py`, find the `FakeDocumentRepository` class. Replace it:

```python
class FakeDocumentRepository:
    def __init__(self) -> None:
        self.documents: list[Document] = []
        self.seen_in_sync_calls: list[tuple[UUID, UUID]] = []  # (document_id, sync_run_id)

    async def get_by_source_kind_path(
        self, source_id: UUID, document_kind: str, logical_path: str | None
    ) -> Document | None:
        return next(
            (
                d
                for d in self.documents
                if d.source_id == source_id
                and d.document_kind == document_kind
                and d.logical_path == logical_path
            ),
            None,
        )

    async def create(self, doc: Document) -> Document:
        self.documents.append(doc)
        return doc

    async def mark_seen_in_sync(self, document_id: UUID, sync_run_id: UUID) -> None:
        self.seen_in_sync_calls.append((document_id, sync_run_id))
```

- [ ] **Step 2: Run existing ingestion unit tests to verify nothing broke**

```bash
python -m pytest tests/unit/ingestion/ -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/ingestion/_fakes.py
git commit -m "feat: add mark_seen_in_sync stub to FakeDocumentRepository"
```

---

## Task 9: TDD — IngestionService sync_run_id propagation

**Files:**
- Create: `tests/unit/ingestion/test_sync_run_tracking.py`
- Modify: `lore/ingestion/service.py`

- [ ] **Step 1: Write failing unit tests**

```python
# tests/unit/ingestion/test_sync_run_tracking.py
"""Verify mark_seen_in_sync is called for every seen document, even if content is unchanged."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from lore.connector_sdk.models import RawExternalObject, SyncResult
from lore.ingestion.service import IngestionService
from tests.unit.ingestion._fakes import (
    FakeDocumentRepository,
    FakeDocumentVersionRepository,
    FakeExternalObjectRepository,
    FakeSourceRepository,
    FakeStubConnector,
)

pytestmark = pytest.mark.unit


def _raw_file(path: str, content: str, conn_id: UUID, repo_id: UUID) -> RawExternalObject:
    payload = {"path": path}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/abc/{path}",
        connection_id=conn_id,
        repository_id=repo_id,
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={"commit_sha": "abc123", "path": path, "owner": "owner", "repo": "repo", "branch": "main"},
    )


async def test_mark_seen_in_sync_called_with_sync_run_id() -> None:
    """mark_seen_in_sync must be called once per document when sync_run_id provided."""
    conn_id, repo_id, sync_run_id = uuid4(), uuid4(), uuid4()
    raw = _raw_file("README.md", "# Hello", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    doc_repo = FakeDocumentRepository()
    svc = IngestionService(
        FakeExternalObjectRepository(),
        FakeSourceRepository(),
        doc_repo,
        FakeDocumentVersionRepository(),
    )

    await svc.ingest_sync_result(sync_result, FakeStubConnector(), sync_run_id=sync_run_id)

    assert len(doc_repo.seen_in_sync_calls) == 1
    _doc_id, called_run_id = doc_repo.seen_in_sync_calls[0]
    assert called_run_id == sync_run_id


async def test_mark_seen_in_sync_called_even_when_content_unchanged() -> None:
    """mark_seen_in_sync must be called even when document version is not created (same hash)."""
    conn_id, repo_id, sync_run_id = uuid4(), uuid4(), uuid4()
    raw = _raw_file("README.md", "# Stable", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    doc_repo = FakeDocumentRepository()
    svc = IngestionService(
        FakeExternalObjectRepository(),
        FakeSourceRepository(),
        doc_repo,
        FakeDocumentVersionRepository(),
    )

    # First call — creates document and version
    await svc.ingest_sync_result(sync_result, FakeStubConnector(), sync_run_id=sync_run_id)
    assert len(doc_repo.seen_in_sync_calls) == 1

    # Second call — same content (no new version), but mark_seen_in_sync still called
    sync_run_id_2 = uuid4()
    await svc.ingest_sync_result(sync_result, FakeStubConnector(), sync_run_id=sync_run_id_2)
    assert len(doc_repo.seen_in_sync_calls) == 2
    assert doc_repo.seen_in_sync_calls[1][1] == sync_run_id_2


async def test_mark_seen_in_sync_not_called_without_sync_run_id() -> None:
    """Legacy import flow (sync_run_id=None) must not call mark_seen_in_sync."""
    conn_id, repo_id = uuid4(), uuid4()
    raw = _raw_file("README.md", "# Hello", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    doc_repo = FakeDocumentRepository()
    svc = IngestionService(
        FakeExternalObjectRepository(),
        FakeSourceRepository(),
        doc_repo,
        FakeDocumentVersionRepository(),
    )

    await svc.ingest_sync_result(sync_result, FakeStubConnector())  # no sync_run_id

    assert len(doc_repo.seen_in_sync_calls) == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/unit/ingestion/test_sync_run_tracking.py -v
```

Expected: `FAILED` — `mark_seen_in_sync` is never called because the service doesn't propagate `sync_run_id` yet.

- [ ] **Step 3: Update IngestionService to propagate sync_run_id**

Replace `lore/ingestion/service.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from lore.ingestion.models import IngestionReport
from lore.schema.document import Document, DocumentVersion
from lore.schema.source import Source, SourceType

if TYPE_CHECKING:
    from lore.connector_sdk.base import BaseConnector
    from lore.connector_sdk.models import CanonicalDocumentDraft, RawExternalObject, SyncResult


def _canonical_source_type(provider: str) -> SourceType:
    if provider in {"github", "gitlab"}:
        return SourceType.GIT_REPO
    if provider == "confluence":
        return SourceType.CONFLUENCE
    return SourceType.UNKNOWN


class IngestionService:
    def __init__(
        self,
        external_object_repo: Any,
        source_repo: Any,
        document_repo: Any,
        document_version_repo: Any,
    ) -> None:
        self._ext_obj_repo = external_object_repo
        self._source_repo = source_repo
        self._doc_repo = document_repo
        self._dv_repo = document_version_repo

    async def ingest_sync_result(
        self,
        sync_result: SyncResult,
        connector: BaseConnector,
        sync_run_id: UUID | None = None,
    ) -> IngestionReport:
        report = IngestionReport(warnings=list(sync_result.warnings))
        for raw in sync_result.raw_objects:
            report.raw_objects_processed += 1
            persisted = await self._upsert_raw_object(raw)
            drafts = connector.normalize(raw)
            for draft in drafts:
                created_doc, created_version = await self._upsert_document(
                    draft, raw, external_object_id=persisted.id, sync_run_id=sync_run_id
                )
                if created_doc:
                    report.documents_created += 1
                if created_version:
                    report.versions_created += 1
                else:
                    report.versions_skipped += 1
        return report

    async def _upsert_raw_object(self, raw: RawExternalObject) -> Any:
        return await self._ext_obj_repo.upsert(raw)

    async def _upsert_document(
        self,
        draft: CanonicalDocumentDraft,
        raw: RawExternalObject,
        external_object_id: UUID,
        sync_run_id: UUID | None = None,
    ) -> tuple[bool, bool]:
        """Return (document_created, version_created)."""
        # 1. Find or create source
        source = await self._source_repo.get_by_external_object_id(external_object_id)
        if source is None:
            now = datetime.now(UTC)
            source = await self._source_repo.create_with_external_object(
                Source(
                    id=uuid4(),
                    source_type_raw=raw.provider,
                    source_type_canonical=_canonical_source_type(raw.provider),
                    origin=draft.provenance.external_url or draft.provenance.external_id,
                    created_at=now,
                    updated_at=now,
                ),
                external_object_id=external_object_id,
            )

        # 2. Find or create document
        doc_created = False
        doc = await self._doc_repo.get_by_source_kind_path(
            source.id,
            draft.document_kind,
            draft.logical_path,
        )
        if doc is None:
            now = datetime.now(UTC)
            doc = await self._doc_repo.create(
                Document(
                    id=uuid4(),
                    source_id=source.id,
                    title=draft.title,
                    path=draft.logical_path or draft.provenance.external_id,
                    document_kind=draft.document_kind,
                    logical_path=draft.logical_path,
                    metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )
            doc_created = True

        # 3. Mark document as seen in this sync — BEFORE checksum check
        #    A file can be unchanged in content but still present; it must update last_seen.
        if sync_run_id is not None:
            await self._doc_repo.mark_seen_in_sync(doc.id, sync_run_id)

        # 4. Check idempotency via checksum
        latest = await self._dv_repo.get_latest_version(doc.id)
        if latest is not None and latest.checksum == draft.content_hash:
            return doc_created, False  # same content — skip version creation

        # 5. Create new version with provenance snapshot in metadata
        max_version = await self._dv_repo.get_max_version(doc.id)
        provenance_snapshot: dict[str, Any] = {
            "external_id": raw.external_id,
            "external_url": raw.external_url,
            "raw_payload_hash": raw.raw_payload_hash,
            "commit_sha": raw.metadata.get("commit_sha"),
            "path": raw.metadata.get("path"),
        }
        await self._dv_repo.create(
            DocumentVersion(
                id=uuid4(),
                document_id=doc.id,
                version=max_version + 1,
                content=draft.content,
                checksum=draft.content_hash,
                version_ref=draft.version_ref,
                source_updated_at=draft.source_updated_at,
                metadata=provenance_snapshot,
                created_at=datetime.now(UTC),
            )
        )
        return doc_created, True
```

- [ ] **Step 4: Run sync_run_tracking tests — expect PASS**

```bash
python -m pytest tests/unit/ingestion/test_sync_run_tracking.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run all ingestion unit tests to verify no regressions**

```bash
python -m pytest tests/unit/ingestion/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/ingestion/test_sync_run_tracking.py lore/ingestion/service.py
git commit -m "feat: propagate sync_run_id through IngestionService, call mark_seen_in_sync"
```

---

## Task 10: Update RepositorySyncService and dependency wiring

**Files:**
- Modify: `lore/sync/service.py`
- Modify: `apps/api/routes/v1/repositories.py`

- [ ] **Step 1: Update RepositorySyncService constructor and sync flow**

Replace `lore/sync/service.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lore.connector_sdk.models import FullSyncRequest
from lore.sync.errors import RepositoryNotFoundError, UnsupportedSyncModeError
from lore.sync.models import RepositorySyncResult

if TYPE_CHECKING:
    from uuid import UUID

    from lore.connector_sdk.registry import ConnectorRegistry
    from lore.infrastructure.db.repositories.document import DocumentRepository
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.infrastructure.db.repositories.repository_sync_run import (
        RepositorySyncRunRepository,
    )
    from lore.ingestion.service import IngestionService


class RepositorySyncService:
    """Provider-agnostic sync lifecycle orchestrator for existing repositories."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        ingestion: IngestionService,
        ext_repo_repo: ExternalRepositoryRepository,
        sync_run_repo: RepositorySyncRunRepository,
        document_repo: DocumentRepository,
    ) -> None:
        self._registry = registry
        self._ingestion = ingestion
        self._ext_repo_repo = ext_repo_repo
        self._sync_run_repo = sync_run_repo
        self._document_repo = document_repo

    async def sync_repository(
        self,
        repository_id: UUID,
        trigger: str = "manual",
        mode: str = "full",
    ) -> RepositorySyncResult:
        if mode != "full":
            raise UnsupportedSyncModeError(mode)

        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        # raises ConnectorNotFoundError if provider not registered
        connector = self._registry.get(repo.provider)

        run = await self._sync_run_repo.create_running(
            repository_id=repo.id,
            connector_id=repo.provider,
            trigger=trigger,
            mode=mode,
        )

        try:
            request = FullSyncRequest(
                connection_id=repo.connection_id,
                repository_id=repo.id,
                resource_uri=repo.html_url,
            )
            sync_result = await connector.full_sync(request)
            report = await self._ingestion.ingest_sync_result(
                sync_result, connector, sync_run_id=run.id
            )

            status = "partial" if report.warnings else "succeeded"

            inactive_count = 0
            if status == "succeeded":
                inactive_count = await self._document_repo.mark_missing_github_files_inactive(
                    repository_id=repo.id,
                    sync_run_id=run.id,
                )

            await self._sync_run_repo.mark_finished(
                run_id=run.id,
                status=status,
                raw_objects_processed=report.raw_objects_processed,
                documents_created=report.documents_created,
                versions_created=report.versions_created,
                versions_skipped=report.versions_skipped,
                warnings=report.warnings,
                metadata={"documents_marked_inactive": inactive_count},
            )
            await self._ext_repo_repo.mark_synced(repo.id, datetime.now(UTC))

            return RepositorySyncResult(
                sync_run_id=run.id,
                repository_id=repo.id,
                status=status,
                trigger=trigger,
                mode=mode,
                raw_objects_processed=report.raw_objects_processed,
                documents_created=report.documents_created,
                versions_created=report.versions_created,
                versions_skipped=report.versions_skipped,
                warnings=report.warnings,
            )

        except Exception as exc:
            await self._sync_run_repo.mark_failed(
                run_id=run.id,
                error_message=str(exc),
            )
            # Known limitation: route handler commits mark_failed and any partial
            # ingestion flushes in one transaction. Acceptable for this PR.
            raise
```

- [ ] **Step 2: Update `_build_sync_service` in routes**

In `apps/api/routes/v1/repositories.py`, find `_build_sync_service` (lines 93-103). Replace it:

```python
def _build_sync_service(
    session: AsyncSession, registry: ConnectorRegistry
) -> RepositorySyncService:
    ext_repo_repo = ExternalRepositoryRepository(session)
    ext_obj_repo = ExternalObjectRepository(session)
    source_repo = SourceRepository(session)
    doc_repo = DocumentRepository(session)
    dv_repo = DocumentVersionRepository(session)
    sync_run_repo = RepositorySyncRunRepository(session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    return RepositorySyncService(registry, ingestion, ext_repo_repo, sync_run_repo, doc_repo)
```

- [ ] **Step 3: Run existing sync integration tests**

```bash
python -m pytest tests/integration/connectors/test_sync_api.py -v
```

Expected: all pass (A through G).

- [ ] **Step 4: Run mypy**

```bash
python -m mypy lore/sync/service.py apps/api/routes/v1/repositories.py --ignore-missing-imports
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add lore/sync/service.py apps/api/routes/v1/repositories.py
git commit -m "feat: inject DocumentRepository into RepositorySyncService, mark inactive on succeeded sync"
```

---

## Task 11: Update RepositoryBriefService

**Files:**
- Modify: `lore/artifacts/repository_brief_service.py`

- [ ] **Step 1: Change the path query in `generate_brief`**

In `lore/artifacts/repository_brief_service.py`, find line 121:

```python
paths = await self._document_repo.get_document_paths_by_repository_id(repository_id)
```

Replace with:

```python
paths = await self._document_repo.get_active_document_paths_by_repository_id(repository_id)
```

That is the only change. Nothing else in this file changes.

- [ ] **Step 2: Run existing artifact tests**

```bash
python -m pytest tests/integration/test_repository_artifact_repository.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add lore/artifacts/repository_brief_service.py
git commit -m "feat: Repository Brief uses get_active_document_paths_by_repository_id"
```

---

## Task 12: Integration tests — Repository Brief excludes inactive documents

**Files:**
- Create: `tests/integration/test_repository_brief_active_documents.py`

- [ ] **Step 1: Create test L**

```python
# tests/integration/test_repository_brief_active_documents.py
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
from lore.infrastructure.db.models.repository_artifact import RepositoryArtifactORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository

pytestmark = pytest.mark.integration


async def _seed_full_repo(session: AsyncSession):
    """Seed connection + repo + one active doc + one inactive doc + succeeded sync run."""
    now = datetime.now(UTC)
    suffix = uuid4().hex[:6]

    conn = ExternalConnectionORM(
        id=uuid4(), provider="github", auth_mode="env_pat",
        metadata_={}, created_at=now, updated_at=now,
    )
    session.add(conn)
    await session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(), connection_id=conn.id, provider="github",
        owner="brieforg", name=f"briefrepo-{suffix}",
        full_name=f"brieforg/briefrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/brieforg/briefrepo-{suffix}",
        metadata_={}, created_at=now, updated_at=now,
    )
    session.add(repo)
    await session.flush()

    run = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id,
        connector_id="github", trigger="manual", mode="full",
        status="succeeded", started_at=now, finished_at=now,
        warnings=[], metadata_={},
    )
    session.add(run)
    await session.flush()

    # Active document — README.md
    eo_readme = ExternalObjectORM(
        id=uuid4(), repository_id=repo.id, connection_id=conn.id,
        provider="github", object_type="github.file",
        external_id=f"brieforg/briefrepo-{suffix}:file:README.md",
        raw_payload_json={}, raw_payload_hash="hash1",
        fetched_at=now, metadata_={},
    )
    session.add(eo_readme)
    await session.flush()

    src_readme = SourceORM(
        id=uuid4(), source_type_raw="github.file", source_type_canonical="github.file",
        origin="github://brieforg/briefrepo/README.md",
        external_object_id=eo_readme.id, created_at=now, updated_at=now,
    )
    session.add(src_readme)
    await session.flush()

    doc_readme = DocumentORM(
        id=uuid4(), source_id=src_readme.id,
        title="README.md", path="README.md", metadata_={},
        created_at=now, updated_at=now, is_active=True,
    )
    session.add(doc_readme)
    await session.flush()

    # Inactive document — deleted.py
    eo_deleted = ExternalObjectORM(
        id=uuid4(), repository_id=repo.id, connection_id=conn.id,
        provider="github", object_type="github.file",
        external_id=f"brieforg/briefrepo-{suffix}:file:deleted.py",
        raw_payload_json={}, raw_payload_hash="hash2",
        fetched_at=now, metadata_={},
    )
    session.add(eo_deleted)
    await session.flush()

    src_deleted = SourceORM(
        id=uuid4(), source_type_raw="github.file", source_type_canonical="github.file",
        origin="github://brieforg/briefrepo/deleted.py",
        external_object_id=eo_deleted.id, created_at=now, updated_at=now,
    )
    session.add(src_deleted)
    await session.flush()

    doc_deleted = DocumentORM(
        id=uuid4(), source_id=src_deleted.id,
        title="deleted.py", path="deleted.py", metadata_={},
        created_at=now, updated_at=now,
        is_active=False, deleted_at=now,
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
```

- [ ] **Step 2: Run test L**

```bash
python -m pytest tests/integration/test_repository_brief_active_documents.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_repository_brief_active_documents.py
git commit -m "test: Repository Brief excludes inactive documents (test L)"
```

---

## Task 13: Integration lifecycle tests — G through K

**Files:**
- Create: `tests/integration/connectors/test_sync_document_lifecycle.py`

These tests exercise the full sync → deactivation → reactivation cycle through the HTTP API.

- [ ] **Step 1: Create lifecycle test file**

```python
# tests/integration/connectors/test_sync_document_lifecycle.py
"""
Document active-state lifecycle tests via the sync HTTP API.

Each test uses a unique owner_suffix (uuid4 slice) to avoid shared state.
MutableFakeConnector uses connector_id="github" to match repository provider.
external_id is derived from owner/repo/path — stable across syncs for the same path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
)
from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.db.models.document import DocumentORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.source import SourceORM

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

LIFECYCLE_PROVIDER = "github"


@dataclass
class _FileConfig:
    path: str
    content: str


class MutableFakeConnector(BaseConnector):
    """Fake connector with mutable file list for lifecycle tests.

    connector_id must be "github" so it matches the repository provider stored at import.
    external_id = "{owner}/{repo}:file:{path}" — stable across syncs for the same path.
    Only content/content_hash change when testing new versions.
    """

    def __init__(self, owner_suffix: str) -> None:
        self._suffix = owner_suffix
        self.files: list[_FileConfig] = []
        self.warnings: list[str] = []
        self._raise_on_sync: Exception | None = None

    @property
    def _owner(self) -> str:
        return f"lc-org-{self._suffix}"

    @property
    def _repo(self) -> str:
        return f"lc-repo-{self._suffix}"

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id=LIFECYCLE_PROVIDER,
            display_name="Lifecycle Fake",
            version="0.0.1",
            capabilities=ConnectorCapabilities(
                supports_full_sync=True,
                supports_incremental_sync=False,
                supports_webhooks=False,
                supports_repository_tree=False,
                supports_files=True,
                supports_issues=False,
                supports_pull_requests=False,
                supports_comments=False,
                supports_releases=False,
                supports_permissions=False,
                object_types=("github.file",),
            ),
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider=LIFECYCLE_PROVIDER,
            owner=self._owner,
            name=self._repo,
            full_name=f"{self._owner}/{self._repo}",
            default_branch="main",
            html_url=f"https://example.com/{self._owner}/{self._repo}",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        if self._raise_on_sync is not None:
            raise self._raise_on_sync

        raw_objects = []
        for fc in self.files:
            payload = {"path": fc.path, "owner": self._owner, "repo": self._repo}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            raw = RawExternalObject(
                provider=LIFECYCLE_PROVIDER,
                object_type="github.file",
                external_id=f"{self._owner}/{self._repo}:file:{fc.path}",
                external_url=f"https://example.com/{self._owner}/{self._repo}/blob/abc/{fc.path}",
                connection_id=request.connection_id,
                repository_id=request.repository_id,
                raw_payload=payload,
                raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                content=fc.content,
                content_hash="sha256:" + hashlib.sha256(fc.content.encode()).hexdigest(),
                source_updated_at=None,
                fetched_at=datetime.now(UTC),
                metadata={
                    "commit_sha": "abc123",
                    "path": fc.path,
                    "owner": self._owner,
                    "repo": self._repo,
                    "branch": "main",
                },
            )
            raw_objects.append(raw)

        return SyncResult(
            connector_id=LIFECYCLE_PROVIDER,
            raw_objects=raw_objects,
            warnings=list(self.warnings),
        )

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _import_repo(
    app: FastAPI, client: AsyncClient, connector: MutableFakeConnector
) -> UUID:
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    url = f"https://example.com/{connector._owner}/{connector._repo}"
    resp = await client.post(
        "/api/v1/repositories/import",
        json={"url": url, "connector_id": LIFECYCLE_PROVIDER},
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()["repository_id"])


async def _sync(
    app: FastAPI, client: AsyncClient, repo_id: UUID, connector: MutableFakeConnector
) -> tuple[int, dict[str, Any]]:
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(f"/api/v1/repositories/{repo_id}/sync")
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


async def _get_doc(
    session: AsyncSession, repo_id: UUID, path: str
) -> DocumentORM | None:
    result = await session.execute(
        select(DocumentORM)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == repo_id)
        .where(DocumentORM.path == path)
    )
    return result.scalar_one_or_none()


# ── G: deleted file → inactive after succeeded sync ──────────────────────────


async def test_g_deleted_file_becomes_inactive(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("README.md", "# Hello"), _FileConfig("src/app.py", "code")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    # sync_1 — both files present
    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1
    assert b1["status"] == "succeeded"

    # sync_2 — app.py removed
    connector.files = [_FileConfig("README.md", "# Hello")]
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200, b2
    assert b2["status"] == "succeeded"

    await db_session.expire_all()
    readme = await _get_doc(db_session, repo_id, "README.md")
    app_py = await _get_doc(db_session, repo_id, "src/app.py")

    assert readme is not None and readme.is_active is True
    assert app_py is not None
    assert app_py.is_active is False
    assert app_py.deleted_at is not None


# ── H: failed sync does not mark files inactive ───────────────────────────────


async def test_h_failed_sync_does_not_mark_inactive(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("README.md", "# Hello"), _FileConfig("src/app.py", "code")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1

    # sync_2 — connector raises
    connector._raise_on_sync = RuntimeError("network failure")
    s2, _ = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 500

    await db_session.expire_all()
    readme = await _get_doc(db_session, repo_id, "README.md")
    app_py = await _get_doc(db_session, repo_id, "src/app.py")

    assert readme is not None and readme.is_active is True
    assert app_py is not None and app_py.is_active is True


# ── I: partial sync does not mark files inactive ──────────────────────────────


async def test_i_partial_sync_does_not_mark_inactive(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("README.md", "# Hello"), _FileConfig("src/app.py", "code")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1

    # sync_2 — returns only README + a warning → partial
    connector.files = [_FileConfig("README.md", "# Hello")]
    connector.warnings = ["rate limit hit — some files skipped"]
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200, b2
    assert b2["status"] == "partial"

    await db_session.expire_all()
    app_py = await _get_doc(db_session, repo_id, "src/app.py")

    assert app_py is not None and app_py.is_active is True


# ── J: reappeared file becomes active again ───────────────────────────────────


async def test_j_reappeared_file_becomes_active(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("src/app.py", "code v1")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1

    # sync_2 — app.py gone → inactive
    connector.files = []
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200 and b2["status"] == "succeeded"

    await db_session.expire_all()
    app_py_after_sync2 = await _get_doc(db_session, repo_id, "src/app.py")
    assert app_py_after_sync2 is not None and app_py_after_sync2.is_active is False

    # sync_3 — app.py reappears
    connector.files = [_FileConfig("src/app.py", "code v1")]
    s3, b3 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s3 == 200 and b3["status"] == "succeeded"
    sync_run_3_id = UUID(b3["sync_run_id"])

    await db_session.expire_all()
    app_py_after_sync3 = await _get_doc(db_session, repo_id, "src/app.py")
    assert app_py_after_sync3 is not None
    assert app_py_after_sync3.is_active is True
    assert app_py_after_sync3.deleted_at is None
    assert app_py_after_sync3.last_seen_sync_run_id == sync_run_3_id


# ── K: unchanged file still updates last_seen_sync_run_id ────────────────────


async def test_k_unchanged_file_updates_last_seen(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)
    content = "# Stable Content"

    connector.files = [_FileConfig("README.md", content)]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200 and b1["status"] == "succeeded"

    # sync_2 — same content, no new DocumentVersion
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200 and b2["status"] == "succeeded"
    assert b2["versions_created"] == 0
    assert b2["versions_skipped"] >= 1
    sync_run_2_id = UUID(b2["sync_run_id"])

    await db_session.expire_all()
    readme = await _get_doc(db_session, repo_id, "README.md")
    assert readme is not None
    assert readme.last_seen_sync_run_id == sync_run_2_id
    assert readme.is_active is True
```

- [ ] **Step 2: Run lifecycle tests G–K**

```bash
python -m pytest tests/integration/connectors/test_sync_document_lifecycle.py -v
```

Expected: 5 passed (G, H, I, J, K).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/connectors/test_sync_document_lifecycle.py
git commit -m "test: sync lifecycle tests G–K (delete/fail/partial/reappear/unchanged)"
```

---

## Task 14: Migration schema test M

**Files:**
- Create: `tests/integration/test_migration_0005.py`

- [ ] **Step 1: Create migration schema test**

```python
# tests/integration/test_migration_0005.py
"""Schema tests for migration 0005 — document active state columns."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def _column_exists(engine, table: str, column: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        return result.scalar() is not None


async def _column_nullable(engine, table: str, column: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        return result.scalar() == "YES"


async def test_m_is_active_column_exists(db_engine) -> None:
    assert await _column_exists(db_engine, "documents", "is_active")


async def test_m_deleted_at_column_exists_and_nullable(db_engine) -> None:
    assert await _column_exists(db_engine, "documents", "deleted_at")
    assert await _column_nullable(db_engine, "documents", "deleted_at")


async def test_m_first_seen_sync_run_id_exists_and_nullable(db_engine) -> None:
    assert await _column_exists(db_engine, "documents", "first_seen_sync_run_id")
    assert await _column_nullable(db_engine, "documents", "first_seen_sync_run_id")


async def test_m_last_seen_sync_run_id_exists_and_nullable(db_engine) -> None:
    assert await _column_exists(db_engine, "documents", "last_seen_sync_run_id")
    assert await _column_nullable(db_engine, "documents", "last_seen_sync_run_id")
```

- [ ] **Step 2: Run migration schema tests**

```bash
python -m pytest tests/integration/test_migration_0005.py -v
```

Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_migration_0005.py
git commit -m "test: migration 0005 schema tests (M)"
```

---

## Task 15: Full test suite

- [ ] **Step 1: Run all unit tests**

```bash
python -m pytest tests/unit/ -v
```

Expected: all pass. Key checks: ingestion idempotency, sync_run_tracking (3 new tests).

- [ ] **Step 2: Run all integration tests**

```bash
python -m pytest tests/integration/ -v
```

Expected: all pass. Key checks: document_active_state (A–F2), sync_document_lifecycle (G–K), repository_brief_active_documents (L), migration_0005 (M), existing paths tests, existing sync API tests.

- [ ] **Step 3: Run type checking**

```bash
python -m mypy lore/ apps/ --ignore-missing-imports
```

Expected: no errors.

- [ ] **Step 4: Run linter**

```bash
python -m ruff check lore/ apps/ tests/
```

Expected: no issues.

- [ ] **Step 5: Final commit if any linter fixes were needed**

```bash
git add -A
git commit -m "fix: ruff/mypy cleanup after PR #6 implementation"
```

---

## Self-Review

### Spec coverage check

| Spec section | Covered by task |
|---|---|
| Migration 0005 (4 columns + 3 indexes) | Task 1 |
| DocumentORM 4 new fields | Task 2 |
| Document schema 4 fields with defaults | Task 3 |
| `_doc_orm_to_schema` + `create` mapping | Task 4 |
| `get_active_document_paths_by_repository_id` | Task 5 |
| `mark_seen_in_sync` with COALESCE | Task 6 |
| `mark_missing_github_files_inactive` with NULL-safe OR | Task 7 |
| FakeDocumentRepository stub | Task 8 |
| IngestionService `sync_run_id` propagation | Task 9 |
| `mark_seen_in_sync` before checksum early-return | Task 9 (service rewrite) |
| RepositorySyncService inject `document_repo` | Task 10 |
| `mark_missing` only on `succeeded` | Task 10 |
| `inactive_count` in `mark_finished` metadata | Task 10 |
| `_build_sync_service` wiring | Task 10 |
| RepositoryBriefService method swap | Task 11 |
| Tests A–F2 | Tasks 5, 6, 7 |
| Tests G–K | Task 13 |
| Test L | Task 12 |
| Test M | Task 14 |
| Legacy import flow (sync_run_id=None) untouched | Task 9 (no sync_run_id path) |
| `result.rowcount or 0` | Task 7 |
| No `.scalar_subquery()` | Task 7 |
| `sa.text("true")` server_default | Task 2 |
| `connector_id="github"` in MutableFakeConnector | Task 13 |
| Stable `external_id` in lifecycle tests | Task 13 (derived from `_owner/_repo/path`) |
| No API contract changes | Verified — `RepositorySyncResponse` unchanged |
| No response model changes for `inactive_count` | Task 10 — stored in `metadata` only |

All spec requirements are covered. No gaps found.
