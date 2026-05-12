# Repository Brief Artifact Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **WORKTREE REQUIRED:** Before starting, create an isolated worktree via `superpowers:using-git-worktrees`. All implementation happens on a feature branch, not on `main`.

**Goal:** Add a deterministic repository brief artifact — generate a structured overview from ingested data, detect staleness after re-sync, expose via two API endpoints.

**Architecture:** New `lore/artifacts/` behavioral slice. `RepositoryBriefService` reads from `ExternalRepositoryRepository`, `RepositorySyncRunRepository`, and `DocumentRepository`; upserts a `RepositoryArtifact` with `source_sync_run_id`. Staleness = `artifact.source_sync_run_id != latest_succeeded_run.id`, computed dynamically at read time.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, PostgreSQL, Alembic, pytest + testcontainers

**Spec:** `docs/superpowers/specs/2026-05-12-repository-brief-design.md`

---

## File Map

**New files:**
| Path | Purpose |
|------|---------|
| `migrations/versions/0004_repository_artifacts.py` | Alembic migration: `repository_artifacts` table |
| `lore/schema/repository_artifact.py` | `RepositoryArtifact` frozen dataclass + `ARTIFACT_TYPE_REPOSITORY_BRIEF` |
| `lore/infrastructure/db/models/repository_artifact.py` | `RepositoryArtifactORM` |
| `lore/infrastructure/db/repositories/repository_artifact.py` | `RepositoryArtifactRepository` |
| `lore/artifacts/__init__.py` | Empty package marker |
| `lore/artifacts/errors.py` | `RepositoryNotSyncedError` |
| `lore/artifacts/repository_brief_models.py` | Content dataclasses + pure categorization functions |
| `lore/artifacts/repository_brief_service.py` | `RepositoryBriefService` |
| `apps/api/routes/v1/repository_artifacts.py` | Route handlers |
| `tests/unit/artifacts/__init__.py` | Empty |
| `tests/unit/artifacts/_fakes.py` | In-memory fake repositories for unit tests |
| `tests/unit/artifacts/test_file_categorization.py` | Unit tests for pure categorization functions |
| `tests/unit/artifacts/test_repository_brief_service.py` | Unit tests for RepositoryBriefService |
| `tests/integration/test_repository_artifact_repository.py` | Integration tests for RepositoryArtifactRepository |
| `tests/integration/test_repository_brief_api.py` | Integration API tests via `app_client_with_db` |

**Modified files:**
| Path | Change |
|------|--------|
| `lore/infrastructure/db/repositories/repository_sync_run.py` | Add `get_latest_succeeded_by_repository` |
| `lore/infrastructure/db/repositories/document.py` | Add `get_document_paths_by_repository_id` |
| `apps/api/main.py` | Register `repository_artifacts_router` |
| `tests/integration/conftest.py` | Add `repository_artifact` model import |

---

### Task 1: Migration — repository_artifacts table

**Files:**
- Create: `migrations/versions/0004_repository_artifacts.py`

- [ ] **Step 1: Write the migration**

```python
# migrations/versions/0004_repository_artifacts.py
"""repository_artifacts — deterministic brief artifacts per repository

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_sync_run_id", sa.UUID(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "artifact_type IN ('repository_brief')",
            name="ck_repository_artifact_type",
        ),
        sa.ForeignKeyConstraint(["repository_id"], ["external_repositories.id"]),
        sa.ForeignKeyConstraint(["source_sync_run_id"], ["repository_sync_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", "artifact_type", name="uq_repository_artifact_type"),
    )
    op.create_index(
        "ix_repository_artifacts_repository_id",
        "repository_artifacts",
        ["repository_id"],
    )
    op.create_index(
        "ix_repository_artifacts_artifact_type",
        "repository_artifacts",
        ["artifact_type"],
    )
    op.create_index(
        "ix_repository_artifacts_source_sync_run_id",
        "repository_artifacts",
        ["source_sync_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_repository_artifacts_source_sync_run_id", "repository_artifacts")
    op.drop_index("ix_repository_artifacts_artifact_type", "repository_artifacts")
    op.drop_index("ix_repository_artifacts_repository_id", "repository_artifacts")
    op.drop_table("repository_artifacts")
```

- [ ] **Step 2: Verify migration syntax; run against DB if available**

If the dev stack is running:
```bash
make migrate
```
Expected: `Running upgrade 0003 -> 0004, repository_artifacts — deterministic brief artifacts`

If no DB is available, verify syntax only:
```bash
python -m py_compile migrations/versions/0004_repository_artifacts.py
```
Do NOT block on infrastructure. Proceed to Step 3 even if DB is unavailable; integration tests will execute the migration via testcontainers.

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/0004_repository_artifacts.py
git commit -m "feat(migration): add repository_artifacts table (0004)"
```

---

### Task 2: Schema dataclass — RepositoryArtifact

**Files:**
- Create: `lore/schema/repository_artifact.py`

- [ ] **Step 1: Write the schema**

```python
# lore/schema/repository_artifact.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003, TCH003
from typing import Any
from uuid import UUID  # noqa: TC003, TCH003

ARTIFACT_TYPE_REPOSITORY_BRIEF = "repository_brief"


@dataclass(frozen=True)
class RepositoryArtifact:
    id: UUID
    repository_id: UUID
    artifact_type: str
    title: str
    content_json: dict[str, Any]
    source_sync_run_id: UUID
    generated_at: datetime
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Write a smoke test**

```python
# tests/unit/test_schema_repository_artifact.py
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF, RepositoryArtifact


def test_artifact_type_constant() -> None:
    assert ARTIFACT_TYPE_REPOSITORY_BRIEF == "repository_brief"


def test_repository_artifact_is_frozen() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    artifact = RepositoryArtifact(
        id=uuid4(),
        repository_id=uuid4(),
        artifact_type=ARTIFACT_TYPE_REPOSITORY_BRIEF,
        title="Test",
        content_json={"schema_version": 1},
        source_sync_run_id=uuid4(),
        generated_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert artifact.artifact_type == "repository_brief"
```

- [ ] **Step 3: Run smoke test**

```bash
make test-unit
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add lore/schema/repository_artifact.py tests/unit/test_schema_repository_artifact.py
git commit -m "feat(schema): add RepositoryArtifact dataclass and ARTIFACT_TYPE_REPOSITORY_BRIEF"
```

---

### Task 3: ORM model — RepositoryArtifactORM

**Files:**
- Create: `lore/infrastructure/db/models/repository_artifact.py`

- [ ] **Step 1: Write the ORM model**

```python
# lore/infrastructure/db/models/repository_artifact.py
from __future__ import annotations

from datetime import datetime  # noqa: TC003, TCH003
from typing import Any
from uuid import UUID, uuid4  # noqa: TC003, TCH003

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class RepositoryArtifactORM(Base):
    __tablename__ = "repository_artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_repositories.id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("repository_sync_runs.id"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("repository_id", "artifact_type", name="uq_repository_artifact_type"),
        CheckConstraint(
            "artifact_type IN ('repository_brief')",
            name="ck_repository_artifact_type",
        ),
        sa.Index("ix_repository_artifacts_repository_id", "repository_id"),
        sa.Index("ix_repository_artifacts_artifact_type", "artifact_type"),
        sa.Index("ix_repository_artifacts_source_sync_run_id", "source_sync_run_id"),
    )
```

- [ ] **Step 2: Write ORM table test**

Add to `tests/unit/test_orm_models.py`:

```python
def test_repository_artifact_orm_table_name() -> None:
    from lore.infrastructure.db.models.repository_artifact import RepositoryArtifactORM
    assert RepositoryArtifactORM.__tablename__ == "repository_artifacts"


def test_repository_artifact_orm_has_required_columns() -> None:
    from lore.infrastructure.db.models.repository_artifact import RepositoryArtifactORM
    cols = {c.name for c in RepositoryArtifactORM.__table__.columns}
    assert "id" in cols
    assert "repository_id" in cols
    assert "artifact_type" in cols
    assert "content_json" in cols
    assert "source_sync_run_id" in cols
    assert "generated_at" in cols
```

- [ ] **Step 3: Run unit tests**

```bash
make test-unit
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add lore/infrastructure/db/models/repository_artifact.py tests/unit/test_orm_models.py
git commit -m "feat(orm): add RepositoryArtifactORM model"
```

---

### Task 4: RepositoryArtifactRepository

**Files:**
- Create: `lore/infrastructure/db/repositories/repository_artifact.py`
- Modify: `tests/integration/conftest.py` (add model import)

- [ ] **Step 1: Update integration conftest to register the new model**

In `tests/integration/conftest.py`, add `repository_artifact` to the model import block:

```python
from lore.infrastructure.db.models import (  # noqa: F401
    chunk,
    document,
    external_connection,
    external_object,
    external_repository,
    repository_artifact,  # ADD THIS LINE
    repository_sync_run,
    source,
)
```

- [ ] **Step 2: Write failing integration test**

Create `tests/integration/test_repository_artifact_repository.py`:

```python
# tests/integration/test_repository_artifact_repository.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF, RepositoryArtifact


async def _seed_repo_with_run(session: AsyncSession) -> tuple[ExternalRepositoryORM, RepositorySyncRunORM]:
    """Create minimal ExternalConnection + ExternalRepository + RepositorySyncRun."""
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


def _make_artifact(repository_id, sync_run_id) -> RepositoryArtifact:
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
@pytest.mark.asyncio
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
@pytest.mark.asyncio
async def test_upsert_updates_no_duplicate(db_session: AsyncSession) -> None:
    repo, run = await _seed_repo_with_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    first = _make_artifact(repo.id, run.id)
    await artifact_repo.upsert(first)

    # upsert again with new sync run id
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
    # Only one artifact should exist
    fetched = await artifact_repo.get_by_repository_and_type(repo.id, ARTIFACT_TYPE_REPOSITORY_BRIEF)
    assert fetched is not None
    assert fetched.source_sync_run_id == run2.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_repository_and_type_returns_none_when_missing(db_session: AsyncSession) -> None:
    artifact_repo = RepositoryArtifactRepository(db_session)
    result = await artifact_repo.get_by_repository_and_type(uuid4(), ARTIFACT_TYPE_REPOSITORY_BRIEF)
    assert result is None
```

- [ ] **Step 3: Run test — confirm it fails**

```bash
make test-integration
```

Expected: `ImportError` or `ModuleNotFoundError` for `RepositoryArtifactRepository`

- [ ] **Step 4: Implement RepositoryArtifactRepository**

```python
# lore/infrastructure/db/repositories/repository_artifact.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from lore.infrastructure.db.models.repository_artifact import RepositoryArtifactORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.repository_artifact import RepositoryArtifact


def _orm_to_schema(orm: RepositoryArtifactORM) -> RepositoryArtifact:
    return RepositoryArtifact(
        id=orm.id,
        repository_id=orm.repository_id,
        artifact_type=orm.artifact_type,
        title=orm.title,
        content_json=dict(orm.content_json),
        source_sync_run_id=orm.source_sync_run_id,
        generated_at=orm.generated_at,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class RepositoryArtifactRepository(BaseRepository[RepositoryArtifactORM]):
    async def upsert(self, artifact: RepositoryArtifact) -> RepositoryArtifact:
        now = datetime.now(UTC)
        stmt = (
            insert(RepositoryArtifactORM)
            .values(
                id=artifact.id,
                repository_id=artifact.repository_id,
                artifact_type=artifact.artifact_type,
                title=artifact.title,
                content_json=artifact.content_json,
                source_sync_run_id=artifact.source_sync_run_id,
                generated_at=artifact.generated_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_repository_artifact_type",
                set_=dict(
                    title=artifact.title,
                    content_json=artifact.content_json,
                    source_sync_run_id=artifact.source_sync_run_id,
                    generated_at=artifact.generated_at,
                    updated_at=now,
                ),
            )
            .returning(RepositoryArtifactORM)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        orm = result.scalar_one()
        return _orm_to_schema(orm)

    async def get_by_repository_and_type(
        self,
        repository_id: UUID,
        artifact_type: str,
    ) -> RepositoryArtifact | None:
        result = await self.session.execute(
            select(RepositoryArtifactORM).where(
                RepositoryArtifactORM.repository_id == repository_id,
                RepositoryArtifactORM.artifact_type == artifact_type,
            )
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
```

- [ ] **Step 5: Run integration tests**

```bash
make test-integration
```

Expected: all 3 new tests PASS

- [ ] **Step 6: Commit**

```bash
git add \
  lore/schema/repository_artifact.py \
  lore/infrastructure/db/models/repository_artifact.py \
  lore/infrastructure/db/repositories/repository_artifact.py \
  tests/integration/conftest.py \
  tests/integration/test_repository_artifact_repository.py
git commit -m "feat(repository): add RepositoryArtifactRepository with upsert and get"
```

---

### Task 5: DocumentRepository — get_document_paths_by_repository_id

**Files:**
- Modify: `lore/infrastructure/db/repositories/document.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/integration/test_repository_artifact_repository.py` (or create a new file `tests/integration/test_document_repository_paths.py`):

```python
# tests/integration/test_document_repository_paths.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.document import DocumentORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import DocumentRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_document_paths_by_repository_id(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)

    conn = ExternalConnectionORM(
        id=uuid4(), provider="github", auth_mode="env_pat",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(conn)
    await db_session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(), connection_id=conn.id, provider="github",
        owner="org", name="repo", full_name="org/repo",
        default_branch="main", html_url="https://github.com/org/repo",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(repo)
    await db_session.flush()

    ext_obj = ExternalObjectORM(
        id=uuid4(), connection_id=conn.id, repository_id=repo.id,
        provider="github", object_type="github.file",
        external_id="org/repo:file:README.md",
        raw_payload_json={}, raw_payload_hash="hash1",
        fetched_at=now, metadata_={},
    )
    db_session.add(ext_obj)
    await db_session.flush()

    source = SourceORM(
        id=uuid4(), source_type_raw="github",
        source_type_canonical="git_repo",
        origin="https://github.com/org/repo",
        external_object_id=ext_obj.id,
        created_at=now, updated_at=now,
    )
    db_session.add(source)
    await db_session.flush()

    doc = DocumentORM(
        id=uuid4(), source_id=source.id,
        title="README.md", path="README.md",
        document_kind="documentation.readme",
        logical_path="README.md",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(doc)
    await db_session.flush()

    doc_repo = DocumentRepository(db_session)
    paths = await doc_repo.get_document_paths_by_repository_id(repo.id)

    assert paths == ["README.md"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_document_paths_excludes_non_github_file_objects(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)

    conn = ExternalConnectionORM(
        id=uuid4(), provider="github", auth_mode="env_pat",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(conn)
    await db_session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(), connection_id=conn.id, provider="github",
        owner="org2", name="repo2", full_name="org2/repo2",
        default_branch="main", html_url="https://github.com/org2/repo2",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(repo)
    await db_session.flush()

    # This external object is github.repository, NOT github.file
    ext_obj = ExternalObjectORM(
        id=uuid4(), connection_id=conn.id, repository_id=repo.id,
        provider="github", object_type="github.repository",
        external_id="org2/repo2:repo",
        raw_payload_json={}, raw_payload_hash="hash_repo",
        fetched_at=now, metadata_={},
    )
    db_session.add(ext_obj)
    await db_session.flush()

    source = SourceORM(
        id=uuid4(), source_type_raw="github",
        source_type_canonical="git_repo",
        origin="https://github.com/org2/repo2",
        external_object_id=ext_obj.id,
        created_at=now, updated_at=now,
    )
    db_session.add(source)
    await db_session.flush()

    doc = DocumentORM(
        id=uuid4(), source_id=source.id,
        title="Repository", path="<repo>",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(doc)
    await db_session.flush()

    doc_repo = DocumentRepository(db_session)
    paths = await doc_repo.get_document_paths_by_repository_id(repo.id)

    assert paths == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_document_paths_returns_empty_for_no_documents(db_session: AsyncSession) -> None:
    doc_repo = DocumentRepository(db_session)
    paths = await doc_repo.get_document_paths_by_repository_id(uuid4())
    assert paths == []
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
make test-integration
```

Expected: `AttributeError: 'DocumentRepository' object has no attribute 'get_document_paths_by_repository_id'`

- [ ] **Step 3: Implement the method**

Add to `DocumentRepository` class in `lore/infrastructure/db/repositories/document.py`:

```python
    async def get_document_paths_by_repository_id(
        self,
        repository_id: UUID,
    ) -> list[str]:
        from lore.infrastructure.db.models.external_object import ExternalObjectORM
        from lore.infrastructure.db.models.source import SourceORM

        result = await self.session.execute(
            select(DocumentORM.path)
            .distinct()
            .join(SourceORM, DocumentORM.source_id == SourceORM.id)
            .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
            .where(
                ExternalObjectORM.repository_id == repository_id,
                ExternalObjectORM.object_type == "github.file",
            )
            .order_by(DocumentORM.path)
        )
        return list(result.scalars().all())
```

Also add `UUID` to the existing imports at the top of `document.py` if not already present:

```python
from uuid import UUID
```

- [ ] **Step 4: Run integration tests**

```bash
make test-integration
```

Expected: all new tests PASS

- [ ] **Step 5: Commit**

```bash
git add \
  lore/infrastructure/db/repositories/document.py \
  tests/integration/test_document_repository_paths.py
git commit -m "feat(repository): add get_document_paths_by_repository_id to DocumentRepository"
```

---

### Task 6: RepositorySyncRunRepository — get_latest_succeeded_by_repository

**Files:**
- Modify: `lore/infrastructure/db/repositories/repository_sync_run.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/integration/test_sync_run_repository_query.py`:

```python
# tests/integration/test_sync_run_repository_query.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository


async def _seed_connection_and_repo(session: AsyncSession):
    now = datetime.now(UTC)
    conn = ExternalConnectionORM(
        id=uuid4(), provider="github", auth_mode="env_pat",
        metadata_={}, created_at=now, updated_at=now,
    )
    session.add(conn)
    await session.flush()
    repo = ExternalRepositoryORM(
        id=uuid4(), connection_id=conn.id, provider="github",
        owner="org", name="q", full_name="org/q",
        default_branch="main", html_url="https://github.com/org/q",
        metadata_={}, created_at=now, updated_at=now,
    )
    session.add(repo)
    await session.flush()
    return repo


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_latest_succeeded_returns_most_recent(db_session: AsyncSession) -> None:
    repo = await _seed_connection_and_repo(db_session)
    now = datetime.now(UTC)

    run1 = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id, connector_id="github",
        trigger="manual", mode="full", status="succeeded",
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=2),
        created_at=now, updated_at=now,
    )
    run2 = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id, connector_id="github",
        trigger="manual", mode="full", status="succeeded",
        started_at=now - timedelta(hours=1),
        finished_at=now - timedelta(hours=1),
        created_at=now, updated_at=now,
    )
    db_session.add_all([run1, run2])
    await db_session.flush()

    run_repo = RepositorySyncRunRepository(db_session)
    result = await run_repo.get_latest_succeeded_by_repository(repo.id)

    assert result is not None
    assert result.id == run2.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_latest_succeeded_ignores_failed(db_session: AsyncSession) -> None:
    repo = await _seed_connection_and_repo(db_session)
    now = datetime.now(UTC)

    succeeded = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id, connector_id="github",
        trigger="manual", mode="full", status="succeeded",
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=2),
        created_at=now, updated_at=now,
    )
    failed = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id, connector_id="github",
        trigger="manual", mode="full", status="failed",
        started_at=now - timedelta(hours=1),
        finished_at=now - timedelta(hours=1),
        created_at=now, updated_at=now,
    )
    db_session.add_all([succeeded, failed])
    await db_session.flush()

    run_repo = RepositorySyncRunRepository(db_session)
    result = await run_repo.get_latest_succeeded_by_repository(repo.id)

    assert result is not None
    assert result.id == succeeded.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_latest_succeeded_returns_none_when_none_exist(db_session: AsyncSession) -> None:
    run_repo = RepositorySyncRunRepository(db_session)
    result = await run_repo.get_latest_succeeded_by_repository(uuid4())
    assert result is None
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
make test-integration
```

Expected: `AttributeError: 'RepositorySyncRunRepository' has no attribute 'get_latest_succeeded_by_repository'`

- [ ] **Step 3: Implement the method**

Add to `RepositorySyncRunRepository` class in `lore/infrastructure/db/repositories/repository_sync_run.py`:

```python
    async def get_latest_succeeded_by_repository(
        self,
        repository_id: UUID,
    ) -> RepositorySyncRun | None:
        result = await self.session.execute(
            select(RepositorySyncRunORM)
            .where(
                RepositorySyncRunORM.repository_id == repository_id,
                RepositorySyncRunORM.status == "succeeded",
            )
            .order_by(
                RepositorySyncRunORM.finished_at.desc().nullslast(),
                RepositorySyncRunORM.started_at.desc(),
            )
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
```

- [ ] **Step 4: Run integration tests**

```bash
make test-integration
```

Expected: all new tests PASS

- [ ] **Step 5: Commit**

```bash
git add \
  lore/infrastructure/db/repositories/repository_sync_run.py \
  tests/integration/test_sync_run_repository_query.py
git commit -m "feat(repository): add get_latest_succeeded_by_repository to RepositorySyncRunRepository"
```

---

### Task 7: Artifacts slice foundation — errors + models + pure functions

**Files:**
- Create: `lore/artifacts/__init__.py`
- Create: `lore/artifacts/errors.py`
- Create: `lore/artifacts/repository_brief_models.py`
- Create: `tests/unit/artifacts/__init__.py`
- Create: `tests/unit/artifacts/test_file_categorization.py`

- [ ] **Step 1: Write failing unit tests for categorization**

First create `tests/unit/artifacts/__init__.py` (empty file).

Create `tests/unit/artifacts/test_file_categorization.py`:

```python
# tests/unit/artifacts/test_file_categorization.py
"""Unit tests for pure file categorization functions in repository_brief_models."""
from lore.artifacts.repository_brief_models import (
    categorize_paths,
    compute_signals,
    count_extensions,
    detect_important_files,
)


# --- categorize_paths ---

def test_empty_paths_returns_zero_counts() -> None:
    result = categorize_paths([])
    assert result.total == 0
    assert result.markdown == 0
    assert result.source == 0
    assert result.config == 0
    assert result.tests == 0


def test_markdown_files_counted() -> None:
    result = categorize_paths(["README.md", "docs/guide.mdx", "src/app.py"])
    assert result.markdown == 2


def test_source_files_counted() -> None:
    result = categorize_paths(["src/app.py", "utils/helper.ts", "main.go", "index.js"])
    assert result.source == 4


def test_config_files_counted() -> None:
    result = categorize_paths(["package.json", "pyproject.toml", "Dockerfile", ".env.example"])
    assert result.config == 4


def test_test_files_counted_by_path_pattern() -> None:
    result = categorize_paths([
        "tests/test_app.py",
        "src/__tests__/app.test.ts",
        "spec/unit/helper_spec.rb",
    ])
    assert result.tests == 3


def test_file_can_match_multiple_categories() -> None:
    # tests/README.md is both markdown and test path
    result = categorize_paths(["tests/README.md"])
    assert result.markdown == 1
    assert result.tests == 1
    assert result.total == 1


def test_contest_solver_is_not_test_file() -> None:
    result = categorize_paths(["src/contest_solver.py"])
    assert result.tests == 0


def test_total_is_path_count_not_category_sum() -> None:
    result = categorize_paths(["README.md", "src/app.py", "package.json"])
    assert result.total == 3


def test_unsupported_extension_does_not_error() -> None:
    result = categorize_paths(["file.xyz", "data.parquet", "image.webp"])
    assert result.total == 3
    assert result.source == 0
    assert result.markdown == 0


# --- detect_important_files ---

def test_readme_md_detected() -> None:
    files = detect_important_files(["README.md"])
    assert len(files) == 1
    assert files[0].kind == "readme"
    assert files[0].path == "README.md"


def test_readme_uppercase_detected() -> None:
    files = detect_important_files(["README.MD"])
    assert any(f.kind == "readme" for f in files)


def test_nested_readme_detected() -> None:
    files = detect_important_files(["docs/README.md"])
    assert any(f.kind == "readme" for f in files)


def test_package_json_detected() -> None:
    files = detect_important_files(["package.json"])
    assert any(f.kind == "package_manifest" for f in files)


def test_pyproject_toml_detected() -> None:
    files = detect_important_files(["pyproject.toml"])
    assert any(f.kind == "package_manifest" for f in files)


def test_requirements_txt_detected() -> None:
    files = detect_important_files(["requirements.txt"])
    assert any(f.kind == "package_manifest" for f in files)


def test_dockerfile_detected_case_insensitive() -> None:
    files = detect_important_files(["Dockerfile"])
    assert any(f.kind == "docker" for f in files)


def test_docker_compose_yml_detected() -> None:
    files = detect_important_files(["docker-compose.yml"])
    assert any(f.kind == "docker" for f in files)


def test_ci_config_detected() -> None:
    files = detect_important_files([".github/workflows/ci.yml"])
    assert any(f.kind == "ci_config" for f in files)


def test_env_example_detected() -> None:
    files = detect_important_files([".env.example"])
    assert any(f.kind == "env_example" for f in files)


def test_tsconfig_detected() -> None:
    files = detect_important_files(["tsconfig.json"])
    assert any(f.kind == "ts_config" for f in files)


def test_eslint_config_detected() -> None:
    files = detect_important_files([".eslintrc.json", "eslint.config.js"])
    kinds = [f.kind for f in files]
    assert kinds.count("lint_config") == 2


def test_unknown_file_not_in_important_files() -> None:
    files = detect_important_files(["src/app.py", "utils/helper.ts"])
    assert files == []


# --- count_extensions ---

def test_extensions_counted_and_sorted_desc() -> None:
    paths = ["a.py", "b.py", "c.ts", "d.md"]
    result = count_extensions(paths)
    # .py appears 2 times, .ts and .md appear 1 time each
    assert result[0].extension == ".py"
    assert result[0].count == 2


def test_no_extension_files_excluded() -> None:
    paths = ["Makefile", "Dockerfile", "README"]
    result = count_extensions(paths)
    assert result == []


def test_extensions_lowercased() -> None:
    paths = ["App.PY", "app.py"]
    result = count_extensions(paths)
    assert result[0].extension == ".py"
    assert result[0].count == 2


# --- compute_signals ---

def test_signals_all_false_for_empty() -> None:
    signals = compute_signals([], 0)
    assert signals.has_readme is False
    assert signals.has_tests is False
    assert signals.has_docker is False
    assert signals.has_ci is False
    assert signals.has_package_manifest is False


def test_has_readme_true_when_readme_present() -> None:
    from lore.artifacts.repository_brief_models import ImportantFileEntry
    files = [ImportantFileEntry(path="README.md", kind="readme")]
    signals = compute_signals(files, 0)
    assert signals.has_readme is True


def test_has_tests_true_when_test_count_nonzero() -> None:
    signals = compute_signals([], test_file_count=3)
    assert signals.has_tests is True
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
make test-unit
```

Expected: `ModuleNotFoundError: No module named 'lore.artifacts'`

- [ ] **Step 3: Implement artifacts slice**

Create `lore/artifacts/__init__.py` (empty file).

Create `lore/artifacts/errors.py`:

```python
# lore/artifacts/errors.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class RepositoryBriefError(Exception):
    pass


class RepositoryNotSyncedError(RepositoryBriefError):
    def __init__(self, repository_id: UUID) -> None:
        super().__init__(
            f"Repository {repository_id} has no successful sync run. "
            "Generate brief requires a completed sync."
        )
```

Create `lore/artifacts/repository_brief_models.py`:

```python
# lore/artifacts/repository_brief_models.py
from __future__ import annotations

import fnmatch
from collections import Counter
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003, TCH003
from pathlib import Path
from typing import Any, Literal
from uuid import UUID  # noqa: TC003, TCH003

RepositoryBriefState = Literal["missing", "fresh", "stale"]

MARKDOWN_EXTENSIONS: frozenset[str] = frozenset({".md", ".mdx"})

SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".ts", ".tsx", ".js", ".jsx", ".py", ".go",
    ".java", ".cs", ".rs", ".rb", ".php", ".cpp",
    ".c", ".h", ".kt", ".swift",
})

_CONFIG_EXACT_NAMES: frozenset[str] = frozenset({
    "package.json", "tsconfig.json", "pyproject.toml",
    "requirements.txt", "poetry.lock", "dockerfile",
    "docker-compose.yml", "docker-compose.yaml", ".env.example",
})

_CONFIG_GLOB_PATTERNS: tuple[str, ...] = (
    "vite.config.*", "next.config.*", "eslint.*", "prettier.*",
)

TEST_PATH_PATTERNS: frozenset[str] = frozenset({"test", "tests", "spec", "__tests__"})

_IMPORTANT_FILE_EXACT: dict[str, str] = {
    "readme.md": "readme",
    "readme.rst": "readme",
    "readme.txt": "readme",
    "readme": "readme",
    "package.json": "package_manifest",
    "pyproject.toml": "package_manifest",
    "requirements.txt": "package_manifest",
    "dockerfile": "docker",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
    "tsconfig.json": "ts_config",
    ".env.example": "env_example",
    ".env.sample": "env_example",
    ".env.dist": "env_example",
}

_IMPORTANT_FILE_GLOB: tuple[tuple[str, str], ...] = (
    ("eslint.*", "lint_config"),
    ("prettier.*", "lint_config"),
)


@dataclass(frozen=True)
class FileCategorization:
    total: int
    markdown: int
    source: int
    config: int
    tests: int


@dataclass(frozen=True)
class LanguageEntry:
    extension: str
    count: int


@dataclass(frozen=True)
class ImportantFileEntry:
    path: str
    kind: str


@dataclass(frozen=True)
class RepositoryBriefSignals:
    has_readme: bool
    has_tests: bool
    has_docker: bool
    has_ci: bool
    has_package_manifest: bool


@dataclass(frozen=True)
class RepositoryBriefServiceResult:
    repository_id: UUID
    exists: bool
    state: RepositoryBriefState
    is_stale: bool | None
    generated_at: datetime | None
    source_sync_run_id: UUID | None
    current_sync_run_id: UUID | None
    content: dict[str, Any] | None
    reason: str | None


def _is_config(name_lower: str, path_lower: str) -> bool:
    if name_lower in _CONFIG_EXACT_NAMES:
        return True
    for pattern in _CONFIG_GLOB_PATTERNS:
        if fnmatch.fnmatch(name_lower, pattern):
            return True
    parts = Path(path_lower).parts
    if len(parts) >= 3 and parts[-3] == ".github" and parts[-2] == "workflows":
        return True
    return False


def _is_test(path_lower: str) -> bool:
    parts = Path(path_lower).parts
    stem = Path(path_lower).stem
    return (
        "tests" in parts
        or "__tests__" in parts
        or stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith(".test")
        or stem.startswith("spec_")
        or stem.endswith("_spec")
        or stem.endswith(".spec")
    )


def categorize_paths(paths: list[str]) -> FileCategorization:
    markdown = source = config = tests = 0
    for path in paths:
        p = Path(path)
        suffix = p.suffix.lower()
        name_lower = p.name.lower()
        path_lower = path.lower()

        if suffix in MARKDOWN_EXTENSIONS:
            markdown += 1
        if suffix in SOURCE_EXTENSIONS:
            source += 1
        if _is_config(name_lower, path_lower):
            config += 1
        if _is_test(path_lower):
            tests += 1

    return FileCategorization(
        total=len(paths),
        markdown=markdown,
        source=source,
        config=config,
        tests=tests,
    )


def detect_important_files(paths: list[str]) -> list[ImportantFileEntry]:
    result: list[ImportantFileEntry] = []
    for path in paths:
        p = Path(path)
        name_lower = p.name.lower()
        path_lower = path.lower()

        # exact name match
        kind = _IMPORTANT_FILE_EXACT.get(name_lower)
        if kind:
            result.append(ImportantFileEntry(path=path, kind=kind))
            continue

        # glob patterns
        matched = False
        for pattern, kind in _IMPORTANT_FILE_GLOB:
            if fnmatch.fnmatch(name_lower, pattern):
                result.append(ImportantFileEntry(path=path, kind=kind))
                matched = True
                break
        if matched:
            continue

        # .github/workflows/* — CI config
        parts = Path(path_lower).parts
        if (
            len(parts) >= 3
            and parts[-3] == ".github"
            and parts[-2] == "workflows"
        ):
            result.append(ImportantFileEntry(path=path, kind="ci_config"))

    return result


def count_extensions(paths: list[str]) -> list[LanguageEntry]:
    counter: Counter[str] = Counter()
    for path in paths:
        suffix = Path(path).suffix.lower()
        if suffix:
            counter[suffix] += 1
    return [LanguageEntry(extension=ext, count=count) for ext, count in counter.most_common()]


def compute_signals(
    important_files: list[ImportantFileEntry],
    test_file_count: int,
) -> RepositoryBriefSignals:
    kinds = {f.kind for f in important_files}
    return RepositoryBriefSignals(
        has_readme="readme" in kinds,
        has_tests=test_file_count > 0,
        has_docker="docker" in kinds,
        has_ci="ci_config" in kinds,
        has_package_manifest="package_manifest" in kinds,
    )


def build_brief_content_dict(
    *,
    repo_name: str,
    repo_full_name: str,
    repo_provider: str,
    repo_default_branch: str,
    repo_url: str,
    sync_run_id: str,
    last_synced_at: datetime | None,
    categorization: FileCategorization,
    languages: list[LanguageEntry],
    important_files: list[ImportantFileEntry],
    signals: RepositoryBriefSignals,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_by": "repository_brief_service",
        "repository": {
            "name": repo_name,
            "full_name": repo_full_name,
            "provider": repo_provider,
            "default_branch": repo_default_branch,
            "url": repo_url,
        },
        "sync": {
            "sync_run_id": sync_run_id,
            "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
            "commit_sha": None,
        },
        "stats": {
            "total_files": categorization.total,
            "markdown_files": categorization.markdown,
            "source_files": categorization.source,
            "config_files": categorization.config,
            "test_files": categorization.tests,
        },
        "languages": [{"extension": e.extension, "count": e.count} for e in languages],
        "important_files": [{"path": f.path, "kind": f.kind} for f in important_files],
        "signals": {
            "has_readme": signals.has_readme,
            "has_tests": signals.has_tests,
            "has_docker": signals.has_docker,
            "has_ci": signals.has_ci,
            "has_package_manifest": signals.has_package_manifest,
        },
    }
```

- [ ] **Step 4: Register errors in `apps/api/exception_handlers.py`**

The project uses a centralized handler that returns `{"error": {"code": ..., "message": ...}}`.
`RepositoryNotFoundError` (from `lore.sync.errors`) and `RepositoryNotSyncedError` (new) are NOT `LoreError`,
so they need their own handler. Add to the bottom of `apps/api/exception_handlers.py`:

```python
from lore.artifacts.errors import RepositoryNotSyncedError
from lore.sync.errors import RepositoryNotFoundError

_DOMAIN_STATUS_MAP: dict[type[Exception], int] = {
    RepositoryNotFoundError: 404,
    RepositoryNotSyncedError: 409,
}

_DOMAIN_CODE_MAP: dict[type[Exception], str] = {
    RepositoryNotFoundError: "repository_not_found",
    RepositoryNotSyncedError: "repository_not_synced",
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status_code = _DOMAIN_STATUS_MAP.get(type(exc), 500)
    code = _DOMAIN_CODE_MAP.get(type(exc), "domain_error")
    logger.warning("lore.domain_error", code=code, message=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": str(exc)}},
    )
```

Then register in `apps/api/main.py` (before `Exception` handler, order matters):

```python
from apps.api.exception_handlers import (
    domain_error_handler,
    lore_exception_handler,
    unhandled_exception_handler,
)
from lore.artifacts.errors import RepositoryNotSyncedError
from lore.sync.errors import RepositoryNotFoundError

# Inside create_app(), after add_middleware:
app.add_exception_handler(RepositoryNotFoundError, domain_error_handler)
app.add_exception_handler(RepositoryNotSyncedError, domain_error_handler)
app.add_exception_handler(LoreError, lore_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
```

Note: the existing `app.add_exception_handler(LoreError, ...)` and `Exception` lines stay, but `RepositoryNotFoundError`/`RepositoryNotSyncedError` must be registered **before** the catch-all `Exception` handler.

- [ ] **Step 5: Run unit tests**

```bash
make test-unit
```

Expected: all categorization tests PASS

- [ ] **Step 6: Commit**

```bash
git add \
  lore/artifacts/__init__.py \
  lore/artifacts/errors.py \
  lore/artifacts/repository_brief_models.py \
  apps/api/exception_handlers.py \
  apps/api/main.py \
  tests/unit/artifacts/__init__.py \
  tests/unit/artifacts/test_file_categorization.py
git commit -m "feat(artifacts): add file categorization models, errors, and exception handlers"
```

---

### Task 8: RepositoryBriefService

**Files:**
- Create: `lore/artifacts/repository_brief_service.py`
- Create: `tests/unit/artifacts/_fakes.py`
- Create: `tests/unit/artifacts/test_repository_brief_service.py`

- [ ] **Step 1: Write failing service unit tests**

Create `tests/unit/artifacts/_fakes.py`:

```python
# tests/unit/artifacts/_fakes.py
# NOTE: ExternalRepository and RepositorySyncRun are domain schema dataclasses (not ORM).
# Verify their actual import paths before running — they live alongside their repository classes.
# If paths differ in your codebase, adapt these imports to match current conventions.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from lore.infrastructure.db.repositories.external_repository import ExternalRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRun
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF, RepositoryArtifact


def _make_repo(repository_id: UUID, *, full_name: str = "org/repo") -> ExternalRepository:
    now = datetime.now(UTC)
    return ExternalRepository(
        id=repository_id,
        connection_id=uuid4(),
        provider="github",
        owner="org",
        name=full_name.split("/")[-1],
        full_name=full_name,
        default_branch="main",
        html_url=f"https://github.com/{full_name}",
        visibility="public",
        last_synced_at=now - timedelta(minutes=5),
        metadata={},
        created_at=now,
        updated_at=now,
    )


def _make_sync_run(
    repository_id: UUID,
    run_id: UUID | None = None,
    *,
    status: str = "succeeded",
    finished_at_offset_seconds: int = 0,
) -> RepositorySyncRun:
    now = datetime.now(UTC)
    finished = now - timedelta(seconds=finished_at_offset_seconds)
    return RepositorySyncRun(
        id=run_id or uuid4(),
        repository_id=repository_id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status=status,
        started_at=finished - timedelta(seconds=10),
        finished_at=finished,
        raw_objects_processed=0,
        documents_created=0,
        versions_created=0,
        versions_skipped=0,
        warnings=[],
        error_message=None,
        metadata={},
        created_at=now,
        updated_at=now,
    )


class FakeExternalRepositoryRepository:
    def __init__(self) -> None:
        self._repos: dict[UUID, ExternalRepository] = {}

    def add(self, repo: ExternalRepository) -> None:
        self._repos[repo.id] = repo

    async def get_by_id(self, id: UUID) -> ExternalRepository | None:
        return self._repos.get(id)


class FakeRepositorySyncRunRepository:
    def __init__(self) -> None:
        self._runs: list[RepositorySyncRun] = []

    def add(self, run: RepositorySyncRun) -> None:
        self._runs.append(run)

    async def get_latest_succeeded_by_repository(
        self, repository_id: UUID
    ) -> RepositorySyncRun | None:
        succeeded = [
            r for r in self._runs
            if r.repository_id == repository_id and r.status == "succeeded"
        ]
        if not succeeded:
            return None
        return max(
            succeeded,
            key=lambda r: (
                r.finished_at or datetime.min.replace(tzinfo=UTC),
                r.started_at or datetime.min.replace(tzinfo=UTC),
            ),
        )


class FakeDocumentRepository:
    def __init__(self) -> None:
        self._paths: dict[UUID, list[str]] = {}

    def set_paths(self, repository_id: UUID, paths: list[str]) -> None:
        self._paths[repository_id] = paths

    async def get_document_paths_by_repository_id(
        self, repository_id: UUID
    ) -> list[str]:
        return sorted(self._paths.get(repository_id, []))


class FakeRepositoryArtifactRepository:
    def __init__(self) -> None:
        self._artifacts: dict[tuple[UUID, str], RepositoryArtifact] = {}
        self.upsert_call_count: int = 0

    async def upsert(self, artifact: RepositoryArtifact) -> RepositoryArtifact:
        self.upsert_call_count += 1
        key = (artifact.repository_id, artifact.artifact_type)
        self._artifacts[key] = artifact
        return artifact

    async def get_by_repository_and_type(
        self, repository_id: UUID, artifact_type: str
    ) -> RepositoryArtifact | None:
        return self._artifacts.get((repository_id, artifact_type))
```

Create `tests/unit/artifacts/test_repository_brief_service.py`:

```python
# tests/unit/artifacts/test_repository_brief_service.py
from __future__ import annotations

from uuid import uuid4

import pytest

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_brief_service import RepositoryBriefService
from lore.sync.errors import RepositoryNotFoundError
from tests.unit.artifacts._fakes import (
    FakeDocumentRepository,
    FakeExternalRepositoryRepository,
    FakeRepositoryArtifactRepository,
    FakeRepositorySyncRunRepository,
    _make_repo,
    _make_sync_run,
)


def _make_service(
    ext_repo_repo: FakeExternalRepositoryRepository | None = None,
    sync_run_repo: FakeRepositorySyncRunRepository | None = None,
    doc_repo: FakeDocumentRepository | None = None,
    artifact_repo: FakeRepositoryArtifactRepository | None = None,
) -> RepositoryBriefService:
    return RepositoryBriefService(
        ext_repo_repo=ext_repo_repo or FakeExternalRepositoryRepository(),
        sync_run_repo=sync_run_repo or FakeRepositorySyncRunRepository(),
        doc_repo=doc_repo or FakeDocumentRepository(),
        artifact_repo=artifact_repo or FakeRepositoryArtifactRepository(),
    )


# --- generate_brief ---

async def test_generate_raises_not_found_when_repo_missing() -> None:
    svc = _make_service()
    with pytest.raises(RepositoryNotFoundError):
        await svc.generate_brief(uuid4())


async def test_generate_raises_409_when_no_succeeded_sync() -> None:
    repo_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))

    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, status="failed"))

    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo)
    with pytest.raises(RepositoryNotSyncedError):
        await svc.generate_brief(repo_id)


async def test_generate_brief_with_zero_files() -> None:
    repo_id = uuid4()
    run_id = uuid4()

    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))

    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))

    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo)
    result = await svc.generate_brief(repo_id)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.is_stale is False
    assert result.content is not None
    assert result.content["stats"]["total_files"] == 0
    assert result.content["schema_version"] == 1


async def test_generate_brief_counts_markdown_files() -> None:
    repo_id = uuid4()
    run_id = uuid4()

    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))

    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))

    doc_repo = FakeDocumentRepository()
    doc_repo.set_paths(repo_id, ["README.md", "docs/guide.md", "src/app.py"])

    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, doc_repo=doc_repo
    )
    result = await svc.generate_brief(repo_id)

    assert result.content["stats"]["markdown_files"] == 2
    assert result.content["stats"]["source_files"] == 1


async def test_generate_brief_counts_source_files() -> None:
    repo_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id))
    doc_repo = FakeDocumentRepository()
    doc_repo.set_paths(repo_id, ["src/app.ts", "src/utils.js", "setup.py", "main.go"])
    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, doc_repo=doc_repo)
    result = await svc.generate_brief(repo_id)
    assert result.content["stats"]["source_files"] == 4


async def test_generate_brief_counts_config_files() -> None:
    repo_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id))
    doc_repo = FakeDocumentRepository()
    doc_repo.set_paths(repo_id, ["package.json", "pyproject.toml"])
    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, doc_repo=doc_repo)
    result = await svc.generate_brief(repo_id)
    assert result.content["stats"]["config_files"] == 2


async def test_generate_brief_counts_test_files() -> None:
    repo_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id))
    doc_repo = FakeDocumentRepository()
    doc_repo.set_paths(repo_id, ["tests/test_app.py", "tests/test_repo.py", "src/main.py"])
    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, doc_repo=doc_repo)
    result = await svc.generate_brief(repo_id)
    assert result.content["stats"]["test_files"] == 2


async def test_generate_brief_detects_important_files() -> None:
    repo_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id))
    doc_repo = FakeDocumentRepository()
    doc_repo.set_paths(repo_id, ["README.md", "package.json", "Dockerfile"])
    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, doc_repo=doc_repo)
    result = await svc.generate_brief(repo_id)
    kinds = {f["kind"] for f in result.content["important_files"]}
    assert "readme" in kinds
    assert "package_manifest" in kinds
    assert "docker" in kinds


async def test_generate_brief_detects_extensions_sorted_desc() -> None:
    repo_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id))
    doc_repo = FakeDocumentRepository()
    doc_repo.set_paths(repo_id, ["a.py", "b.py", "c.py", "d.ts"])
    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, doc_repo=doc_repo)
    result = await svc.generate_brief(repo_id)
    langs = result.content["languages"]
    assert langs[0]["extension"] == ".py"
    assert langs[0]["count"] == 3


async def test_generate_brief_stores_source_sync_run_id() -> None:
    repo_id = uuid4()
    run_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, artifact_repo=artifact_repo
    )
    result = await svc.generate_brief(repo_id)
    assert result.source_sync_run_id == run_id


async def test_generate_returns_fresh_immediately() -> None:
    repo_id = uuid4()
    run_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))
    svc = _make_service(ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo)
    result = await svc.generate_brief(repo_id)
    assert result.is_stale is False
    assert result.state == "fresh"


async def test_generate_is_idempotent_no_duplicate() -> None:
    repo_id = uuid4()
    run_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, artifact_repo=artifact_repo
    )
    r1 = await svc.generate_brief(repo_id)
    r2 = await svc.generate_brief(repo_id)
    assert artifact_repo.upsert_call_count == 2
    assert r1.source_sync_run_id == r2.source_sync_run_id


# --- get_brief ---

async def test_get_brief_returns_missing_when_no_artifact() -> None:
    repo_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    svc = _make_service(ext_repo_repo=ext_repo_repo)
    result = await svc.get_brief(repo_id)
    assert result.exists is False
    assert result.state == "missing"
    assert result.reason == "brief_not_generated"


async def test_get_brief_returns_fresh_when_sync_run_matches() -> None:
    repo_id = uuid4()
    run_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, artifact_repo=artifact_repo
    )
    await svc.generate_brief(repo_id)
    result = await svc.get_brief(repo_id)
    assert result.is_stale is False
    assert result.state == "fresh"


async def test_get_brief_returns_stale_after_new_sync_run() -> None:
    repo_id = uuid4()
    run_id_1 = uuid4()
    run_id_2 = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    # first sync run
    sync_run_repo.add(_make_sync_run(repo_id, run_id_1, finished_at_offset_seconds=100))
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, artifact_repo=artifact_repo
    )
    await svc.generate_brief(repo_id)

    # simulate a new succeeded sync run (newer)
    sync_run_repo.add(_make_sync_run(repo_id, run_id_2, finished_at_offset_seconds=0))

    result = await svc.get_brief(repo_id)
    assert result.is_stale is True
    assert result.state == "stale"
    assert result.current_sync_run_id == run_id_2


async def test_failed_sync_does_not_make_brief_stale() -> None:
    repo_id = uuid4()
    run_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, artifact_repo=artifact_repo
    )
    await svc.generate_brief(repo_id)

    # Add a failed sync run (should be ignored for stale computation)
    sync_run_repo.add(_make_sync_run(repo_id, status="failed", finished_at_offset_seconds=0))

    result = await svc.get_brief(repo_id)
    assert result.is_stale is False
    assert result.state == "fresh"


async def test_new_succeeded_sync_same_content_makes_stale() -> None:
    """Staleness is sync-run based, not content-diff based."""
    repo_id = uuid4()
    run_id_1 = uuid4()
    run_id_2 = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id_1, finished_at_offset_seconds=100))
    doc_repo = FakeDocumentRepository()
    doc_repo.set_paths(repo_id, ["README.md"])  # same paths in both syncs
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo,
        doc_repo=doc_repo, artifact_repo=artifact_repo,
    )
    await svc.generate_brief(repo_id)

    # new sync run, same content
    sync_run_repo.add(_make_sync_run(repo_id, run_id_2, finished_at_offset_seconds=0))

    result = await svc.get_brief(repo_id)
    assert result.is_stale is True


async def test_orphaned_artifact_no_sync_run_returns_stale() -> None:
    """Artifact exists but no succeeded sync run: stale with current_sync_run_id=None."""
    repo_id = uuid4()
    run_id = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id))
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, artifact_repo=artifact_repo
    )
    await svc.generate_brief(repo_id)

    # Now remove all succeeded runs (simulate orphaned state)
    sync_run_repo._runs.clear()

    result = await svc.get_brief(repo_id)
    assert result.is_stale is True
    assert result.current_sync_run_id is None


async def test_regenerate_makes_fresh_again() -> None:
    repo_id = uuid4()
    run_id_1 = uuid4()
    run_id_2 = uuid4()
    ext_repo_repo = FakeExternalRepositoryRepository()
    ext_repo_repo.add(_make_repo(repo_id))
    sync_run_repo = FakeRepositorySyncRunRepository()
    sync_run_repo.add(_make_sync_run(repo_id, run_id_1, finished_at_offset_seconds=100))
    artifact_repo = FakeRepositoryArtifactRepository()
    svc = _make_service(
        ext_repo_repo=ext_repo_repo, sync_run_repo=sync_run_repo, artifact_repo=artifact_repo
    )
    await svc.generate_brief(repo_id)
    sync_run_repo.add(_make_sync_run(repo_id, run_id_2, finished_at_offset_seconds=0))

    # Brief is now stale — regenerate
    await svc.generate_brief(repo_id)
    result = await svc.get_brief(repo_id)
    assert result.is_stale is False
    assert result.state == "fresh"
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
make test-unit
```

Expected: `ModuleNotFoundError: No module named 'lore.artifacts.repository_brief_service'`

- [ ] **Step 3: Implement RepositoryBriefService**

Create `lore/artifacts/repository_brief_service.py`:

```python
# lore/artifacts/repository_brief_service.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_brief_models import (
    RepositoryBriefServiceResult,
    build_brief_content_dict,
    categorize_paths,
    compute_signals,
    count_extensions,
    detect_important_files,
)
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF, RepositoryArtifact
from lore.sync.errors import RepositoryNotFoundError

if TYPE_CHECKING:
    from lore.infrastructure.db.repositories.document import DocumentRepository
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.infrastructure.db.repositories.repository_artifact import (
        RepositoryArtifactRepository,
    )
    from lore.infrastructure.db.repositories.repository_sync_run import (
        RepositorySyncRunRepository,
    )


class RepositoryBriefService:
    def __init__(
        self,
        ext_repo_repo: ExternalRepositoryRepository,
        sync_run_repo: RepositorySyncRunRepository,
        doc_repo: DocumentRepository,
        artifact_repo: RepositoryArtifactRepository,
    ) -> None:
        self._ext_repo_repo = ext_repo_repo
        self._sync_run_repo = sync_run_repo
        self._doc_repo = doc_repo
        self._artifact_repo = artifact_repo

    async def generate_brief(self, repository_id: UUID) -> RepositoryBriefServiceResult:
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)
        if latest_run is None:
            raise RepositoryNotSyncedError(repository_id)

        paths = await self._doc_repo.get_document_paths_by_repository_id(repository_id)

        categorization = categorize_paths(paths)
        important_files = detect_important_files(paths)
        languages = count_extensions(paths)
        signals = compute_signals(important_files, categorization.tests)

        content = build_brief_content_dict(
            repo_name=repo.name,
            repo_full_name=repo.full_name,
            repo_provider=repo.provider,
            repo_default_branch=repo.default_branch,
            repo_url=repo.html_url,
            sync_run_id=str(latest_run.id),
            last_synced_at=repo.last_synced_at,
            categorization=categorization,
            languages=languages,
            important_files=important_files,
            signals=signals,
        )

        now = datetime.now(UTC)
        artifact = RepositoryArtifact(
            id=uuid4(),
            repository_id=repository_id,
            artifact_type=ARTIFACT_TYPE_REPOSITORY_BRIEF,
            title=f"Repository Brief: {repo.full_name}",
            content_json=content,
            source_sync_run_id=latest_run.id,
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        saved = await self._artifact_repo.upsert(artifact)

        return RepositoryBriefServiceResult(
            repository_id=repository_id,
            exists=True,
            state="fresh",
            is_stale=False,
            generated_at=saved.generated_at,
            source_sync_run_id=saved.source_sync_run_id,
            current_sync_run_id=latest_run.id,
            content=saved.content_json,
            reason=None,
        )

    async def get_brief(self, repository_id: UUID) -> RepositoryBriefServiceResult:
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        artifact = await self._artifact_repo.get_by_repository_and_type(
            repository_id, ARTIFACT_TYPE_REPOSITORY_BRIEF
        )
        if artifact is None:
            return RepositoryBriefServiceResult(
                repository_id=repository_id,
                exists=False,
                state="missing",
                is_stale=None,
                generated_at=None,
                source_sync_run_id=None,
                current_sync_run_id=None,
                content=None,
                reason="brief_not_generated",
            )

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)

        if latest_run is None or artifact.source_sync_run_id != latest_run.id:
            is_stale = True
            state = "stale"
        else:
            is_stale = False
            state = "fresh"

        return RepositoryBriefServiceResult(
            repository_id=repository_id,
            exists=True,
            state=state,
            is_stale=is_stale,
            generated_at=artifact.generated_at,
            source_sync_run_id=artifact.source_sync_run_id,
            current_sync_run_id=latest_run.id if latest_run else None,
            content=artifact.content_json,
            reason=None,
        )
```

- [ ] **Step 4: Run unit tests**

```bash
make test-unit
```

Expected: all service unit tests PASS

- [ ] **Step 5: Commit**

```bash
git add \
  lore/artifacts/repository_brief_service.py \
  tests/unit/artifacts/_fakes.py \
  tests/unit/artifacts/test_repository_brief_service.py
git commit -m "feat(artifacts): implement RepositoryBriefService with generate and get"
```

---

### Task 9: API routes — repository_artifacts.py

**Files:**
- Create: `apps/api/routes/v1/repository_artifacts.py`
- Create: `tests/integration/test_repository_brief_api.py`

- [ ] **Step 1: Write failing integration API tests**

Create `tests/integration/test_repository_brief_api.py`:

```python
# tests/integration/test_repository_brief_api.py
"""Integration API tests for repository brief endpoints.

Uses app_client_with_db (real testcontainer PostgreSQL + ASGI client).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM


async def _seed_repo_with_succeeded_run(
    db_session: AsyncSession,
) -> tuple[ExternalRepositoryORM, RepositorySyncRunORM]:
    now = datetime.now(UTC)
    conn = ExternalConnectionORM(
        id=uuid4(), provider="github", auth_mode="env_pat",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(conn)
    await db_session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(), connection_id=conn.id, provider="github",
        owner="api_org", name="api_repo", full_name="api_org/api_repo",
        default_branch="main", html_url="https://github.com/api_org/api_repo",
        last_synced_at=now, metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(repo)
    await db_session.flush()

    run = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id, connector_id="github",
        trigger="manual", mode="full", status="succeeded",
        started_at=now, finished_at=now,
        created_at=now, updated_at=now,
    )
    db_session.add(run)
    await db_session.flush()

    return repo, run


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_brief_returns_missing_when_not_generated(
    app_client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    repo, _ = await _seed_repo_with_succeeded_run(db_session)

    response = await app_client_with_db.get(f"/api/v1/repositories/{repo.id}/brief")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["state"] == "missing"
    assert body["reason"] == "brief_not_generated"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_brief_returns_404_for_unknown_repository(
    app_client_with_db: AsyncClient,
) -> None:
    response = await app_client_with_db.get(f"/api/v1/repositories/{uuid4()}/brief")
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_generate_returns_409_when_no_succeeded_sync(
    app_client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    conn = ExternalConnectionORM(
        id=uuid4(), provider="github", auth_mode="env_pat",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(conn)
    await db_session.flush()
    repo = ExternalRepositoryORM(
        id=uuid4(), connection_id=conn.id, provider="github",
        owner="norun_org", name="norun_repo", full_name="norun_org/norun_repo",
        default_branch="main", html_url="https://github.com/norun_org/norun_repo",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(repo)
    await db_session.flush()

    response = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "repository_not_synced"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_generate_creates_brief(
    app_client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    repo, _ = await _seed_repo_with_succeeded_run(db_session)

    response = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["state"] == "fresh"
    assert body["is_stale"] is False
    assert body["brief"]["schema_version"] == 1
    assert body["brief"]["repository"]["full_name"] == "api_org/api_repo"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_brief_returns_fresh_after_generation(
    app_client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    repo, _ = await _seed_repo_with_succeeded_run(db_session)
    await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")

    response = await app_client_with_db.get(f"/api/v1/repositories/{repo.id}/brief")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["state"] == "fresh"
    assert body["is_stale"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_brief_returns_stale_after_new_sync_run(
    app_client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    repo, _ = await _seed_repo_with_succeeded_run(db_session)
    await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")

    # Simulate a new sync run
    now = datetime.now(UTC)
    new_run = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id, connector_id="github",
        trigger="manual", mode="full", status="succeeded",
        started_at=now, finished_at=now,
        created_at=now, updated_at=now,
    )
    db_session.add(new_run)
    await db_session.flush()

    response = await app_client_with_db.get(f"/api/v1/repositories/{repo.id}/brief")
    assert response.status_code == 200
    body = response.json()
    assert body["is_stale"] is True
    assert body["state"] == "stale"
    assert body["current_sync_run_id"] == str(new_run.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_generate_makes_stale_brief_fresh_again(
    app_client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    repo, _ = await _seed_repo_with_succeeded_run(db_session)
    await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")

    now = datetime.now(UTC)
    new_run = RepositorySyncRunORM(
        id=uuid4(), repository_id=repo.id, connector_id="github",
        trigger="manual", mode="full", status="succeeded",
        started_at=now, finished_at=now, created_at=now, updated_at=now,
    )
    db_session.add(new_run)
    await db_session.flush()

    await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    response = await app_client_with_db.get(f"/api/v1/repositories/{repo.id}/brief")
    body = response.json()
    assert body["is_stale"] is False
    assert body["state"] == "fresh"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_generate_counts_github_file_documents(
    app_client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    """Full path: real DocumentORM with github.file object type → stats and signals."""
    from lore.infrastructure.db.models.document import DocumentORM
    from lore.infrastructure.db.models.external_object import ExternalObjectORM
    from lore.infrastructure.db.models.source import SourceORM

    repo, _ = await _seed_repo_with_succeeded_run(db_session)
    now = datetime.now(UTC)

    ext_obj = ExternalObjectORM(
        id=uuid4(), connection_id=repo.connection_id, repository_id=repo.id,
        provider="github", object_type="github.file",
        external_id=f"{repo.full_name}:file:README.md",
        raw_payload_json={}, raw_payload_hash="h1",
        fetched_at=now, metadata_={},
    )
    db_session.add(ext_obj)
    await db_session.flush()

    source = SourceORM(
        id=uuid4(), source_type_raw="github", source_type_canonical="git_repo",
        origin=repo.html_url, external_object_id=ext_obj.id,
        created_at=now, updated_at=now,
    )
    db_session.add(source)
    await db_session.flush()

    doc = DocumentORM(
        id=uuid4(), source_id=source.id,
        title="README.md", path="README.md",
        document_kind="documentation.readme",
        logical_path="README.md",
        metadata_={}, created_at=now, updated_at=now,
    )
    db_session.add(doc)
    await db_session.flush()

    response = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/brief/generate")
    assert response.status_code == 200
    body = response.json()
    assert body["brief"]["stats"]["total_files"] == 1
    assert body["brief"]["signals"]["has_readme"] is True
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
make test-integration
```

Expected: `404 Not Found` for all brief endpoints (routes not registered yet)

- [ ] **Step 3: Implement the route file**

Create `apps/api/routes/v1/repository_artifacts.py`:

```python
# apps/api/routes/v1/repository_artifacts.py
# RepositoryNotFoundError and RepositoryNotSyncedError are handled by domain_error_handler
# registered in apps/api/main.py — do NOT catch them here.
from __future__ import annotations

from datetime import datetime  # noqa: TCH003
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID  # noqa: TCH003

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lore.artifacts.repository_brief_models import RepositoryBriefServiceResult
from lore.artifacts.repository_brief_service import RepositoryBriefService
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.infrastructure.db.session import get_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/repositories", tags=["repository_artifacts"])

SessionDep = Annotated["AsyncSession", Depends(get_session)]


class RepositoryBriefMissingResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_BRIEF
    exists: bool = False
    state: Literal["missing"] = "missing"
    reason: str = "brief_not_generated"


class RepositoryBriefPresentResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_BRIEF
    exists: bool = True
    state: Literal["fresh", "stale"]
    is_stale: bool
    generated_at: datetime
    source_sync_run_id: UUID
    current_sync_run_id: UUID | None
    brief: dict[str, Any]


def _build_brief_service(session: AsyncSession) -> RepositoryBriefService:
    return RepositoryBriefService(
        ext_repo_repo=ExternalRepositoryRepository(session),
        sync_run_repo=RepositorySyncRunRepository(session),
        doc_repo=DocumentRepository(session),
        artifact_repo=RepositoryArtifactRepository(session),
    )


def _to_response(
    result: RepositoryBriefServiceResult,
) -> RepositoryBriefMissingResponse | RepositoryBriefPresentResponse:
    if not result.exists:
        return RepositoryBriefMissingResponse(repository_id=result.repository_id)
    return RepositoryBriefPresentResponse(
        repository_id=result.repository_id,
        state=result.state,
        is_stale=result.is_stale,
        generated_at=result.generated_at,
        source_sync_run_id=result.source_sync_run_id,
        current_sync_run_id=result.current_sync_run_id,
        brief=result.content,
    )


@router.get("/{repository_id}/brief")
async def get_repository_brief(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryBriefMissingResponse | RepositoryBriefPresentResponse:
    svc = _build_brief_service(session)
    result = await svc.get_brief(repository_id)
    return _to_response(result)


@router.post("/{repository_id}/brief/generate")
async def generate_repository_brief(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryBriefPresentResponse:
    svc = _build_brief_service(session)
    result = await svc.generate_brief(repository_id)
    await session.commit()
    return _to_response(result)
```

- [ ] **Step 4: Register the router in main.py**

In `apps/api/main.py`, add the import and include the router:

```python
from apps.api.routes.v1.connectors import router as connectors_router
from apps.api.routes.v1.health import router as health_router
from apps.api.routes.v1.repositories import router as repositories_router
from apps.api.routes.v1.repository_artifacts import router as repository_artifacts_router  # ADD

# ...inside create_app():
    api_v1.include_router(health_router)
    api_v1.include_router(connectors_router)
    api_v1.include_router(repositories_router)
    api_v1.include_router(repository_artifacts_router)  # ADD
```

- [ ] **Step 5: Run integration API tests**

```bash
make test-integration
```

Expected: all 8 new API tests PASS

- [ ] **Step 6: Commit**

```bash
git add \
  apps/api/routes/v1/repository_artifacts.py \
  apps/api/main.py \
  tests/integration/test_repository_brief_api.py
git commit -m "feat(api): add GET /brief and POST /brief/generate endpoints"
```

Note: `apps/api/exception_handlers.py` was committed in Task 7. `apps/api/main.py` is modified twice (Task 7: handlers; Task 9: router). Stage it here with the router registration.

---

### Task 10: Final quality pass

**Files:** (no new files)

- [ ] **Step 1: Run formatter**

```bash
make format
```

Expected: reformats any style inconsistencies

- [ ] **Step 2: Run linter**

```bash
make lint
```

Expected: no errors. Fix any issues before proceeding.

- [ ] **Step 3: Run type checker**

```bash
make type-check
```

Expected: no errors. `_to_response` is already typed; no `type: ignore` needed.

- [ ] **Step 4: Run all tests**

```bash
make test-unit && make test-integration
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(types): resolve mypy and ruff issues in repository brief implementation"
```

---

### Task 11: Critical self-review checklist

Before finishing, verify each item:

- [ ] `GitHubConnector` was NOT modified — no persistence added there
- [ ] No LLM, embedding, or semantic search code in any new file
- [ ] `source_sync_run_id` is NOT NULL in both migration and ORM model
- [ ] `content_json` has no `DEFAULT '{}'` in migration
- [ ] `artifact_type IN ('repository_brief')` CHECK constraint is present in migration
- [ ] `object_type = 'github.file'` filter is in `get_document_paths_by_repository_id`
- [ ] `schema_version: 1` and `generated_by: "repository_brief_service"` are in every generated brief
- [ ] `ARTIFACT_TYPE_REPOSITORY_BRIEF` constant is used everywhere (not raw string `"repository_brief"`)
- [ ] `commit_sha` is always `null` in generated briefs
- [ ] `get_latest_succeeded_by_repository` uses only `status = 'succeeded'` (not `partial`)
- [ ] `failed` sync run test passes (stale stays false)
- [ ] `same content new sync makes stale` test passes (sync-run based, not content-diff)
- [ ] `POST /brief/generate` returns `409` with `error.code = "repository_not_synced"` when no sync
- [ ] `409` response body shape: `{"error": {"code": "repository_not_synced", "message": ...}}` (NOT `{"detail": {...}}`)
- [ ] `404` response body shape for unknown repo: `{"error": {"code": "repository_not_found", ...}}`
- [ ] `RepositoryNotFoundError` and `RepositoryNotSyncedError` are NOT caught in route handlers — handled by `domain_error_handler`
- [ ] Upsert uses `ON CONFLICT DO UPDATE` (PostgreSQL atomic, no select-then-insert)
- [ ] Upsert test: second call does NOT create a second row (UNIQUE constraint + upsert semantics)
- [ ] `_is_test` uses path parts, NOT substring match (to avoid false positives like `contest_solver.py`)
- [ ] `_is_config` has ONE `.github/workflows` check (not duplicate)
- [ ] `RepositoryBriefState = Literal["missing", "fresh", "stale"]` used in `RepositoryBriefServiceResult.state`
- [ ] API integration test with real `DocumentORM` + `github.file` `ExternalObjectORM` passes
- [ ] Integration conftest imports `repository_artifact` module

---

## Execution Notes

### Commit discipline

Commit **only after the task's tests pass**. If tests cannot run because infrastructure (Docker/DB) is unavailable, do NOT commit; record the reason in the final summary and proceed — integration tests via testcontainers will validate the code. Never commit a state where tests are known to fail.

### Known limitation (document in brief service)

Add a comment in `generate_brief` before `get_document_paths_by_repository_id`:

```python
# Known limitation: ingestion does not remove DocumentORM records for files deleted
# from GitHub. Brief may include paths no longer present upstream. See spec §13.
paths = await self._doc_repo.get_document_paths_by_repository_id(repository_id)
```

### Manual verification flow

```bash
# 1. Start dev stack
make dev

# 2. Import a repository
curl -X POST http://localhost:8000/api/v1/repositories/import \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/Isqanderm/lore", "connector_id": "github"}'
# Note: repository_id from response

# 3. Sync (if not auto-synced by import)
curl -X POST http://localhost:8000/api/v1/repositories/{id}/sync

# 4. Generate brief
curl -X POST http://localhost:8000/api/v1/repositories/{id}/brief/generate

# 5. Read brief (state: fresh)
curl http://localhost:8000/api/v1/repositories/{id}/brief

# 6. Sync again
curl -X POST http://localhost:8000/api/v1/repositories/{id}/sync

# 7. Read brief (state: stale)
curl http://localhost:8000/api/v1/repositories/{id}/brief

# 8. Regenerate
curl -X POST http://localhost:8000/api/v1/repositories/{id}/brief/generate

# 9. Read brief (state: fresh)
curl http://localhost:8000/api/v1/repositories/{id}/brief
```
