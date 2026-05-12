# Repository Sync Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add provider-agnostic repository sync lifecycle (`repository_sync_runs` table, `RepositorySyncService`, `POST /sync`, `GET /sync-runs`) for already-imported repositories.

**Architecture:** A new `lore/sync/` domain module contains `RepositorySyncService` (orchestrates: load repo → load connector → record run → full_sync → ingest → mark finished/failed). The service is purely provider-agnostic; `GitHubConnector` and `IngestionService` are unchanged. A new `repository_sync_runs` table persists every sync run lifecycle with counters and status.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy async (Mapped style), Alembic, PostgreSQL/pgvector, pytest-asyncio, testcontainers, httpx AsyncClient.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `migrations/versions/<next>_repository_sync_runs.py` | Create | DDL for `repository_sync_runs` table + indexes |
| `lore/infrastructure/db/models/repository_sync_run.py` | Create | `RepositorySyncRunORM` (SQLAlchemy Mapped) |
| `lore/infrastructure/db/repositories/repository_sync_run.py` | Create | `RepositorySyncRun` dataclass + `RepositorySyncRunRepository` |
| `lore/sync/__init__.py` | Create | Empty package marker |
| `lore/sync/errors.py` | Create | `RepositoryNotFoundError`, `UnsupportedSyncModeError` |
| `lore/sync/models.py` | Create | `RepositorySyncResult` dataclass |
| `lore/sync/service.py` | Create | `RepositorySyncService` |
| `tests/integration/connectors/test_sync_api.py` | Create | Integration tests A–G |
| `apps/api/routes/v1/repositories.py` | Modify | Add POST /sync + GET /sync-runs endpoints + schemas + builder |
| `tests/integration/conftest.py` | Modify | Add `repository_sync_run` model import for DDL creation |

---

## Task 1: DB Migration — `repository_sync_runs`

**Files:**
- Create: `migrations/versions/<next>_repository_sync_runs.py` — filename and revision determined in Step 1

- [ ] **Step 1: Verify current migration head before writing the file**

```bash
ls migrations/versions/
```

Expected: two files — `0001_initial_schema.py` and `0002_integration_layer.py`.
If the last file is `0002_…`, the next revision is `0003` and `down_revision = "0002"`.
If the listing shows a different last migration, adjust `revision` and `down_revision` accordingly in the file below.

- [ ] **Step 2: Write migration file**

Create `migrations/versions/0003_repository_sync_runs.py`.

> **If the current Alembic head is NOT `0002`, do not use the code below literally.**
> Update the filename, `revision`, `down_revision`, and the docstring to match the actual head before writing.

```python
# migrations/versions/0003_repository_sync_runs.py
"""repository_sync_runs — sync run lifecycle tracking

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_sync_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_objects_processed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "documents_created",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "versions_created",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "versions_skipped",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.ForeignKeyConstraint(["repository_id"], ["external_repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repository_sync_runs_repository_id_created_at",
        "repository_sync_runs",
        ["repository_id", "created_at"],
    )
    op.create_index(
        "ix_repository_sync_runs_repository_id_status",
        "repository_sync_runs",
        ["repository_id", "status"],
    )
    op.create_index(
        "ix_repository_sync_runs_connector_id",
        "repository_sync_runs",
        ["connector_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_repository_sync_runs_connector_id", "repository_sync_runs")
    op.drop_index("ix_repository_sync_runs_repository_id_status", "repository_sync_runs")
    op.drop_index("ix_repository_sync_runs_repository_id_created_at", "repository_sync_runs")
    op.drop_table("repository_sync_runs")
```

- [ ] **Step 3: Verify migration parses cleanly**

```bash
python -c "import importlib.util; spec = importlib.util.spec_from_file_location('m', 'migrations/versions/0003_repository_sync_runs.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('migration ok')"
```

Expected: `migration ok`

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/*_repository_sync_runs.py
git commit -m "feat(db): add repository_sync_runs migration"
```

---

## Task 2: ORM Model + conftest update

**Files:**
- Create: `lore/infrastructure/db/models/repository_sync_run.py`
- Modify: `tests/integration/conftest.py`

> **Note on `lore/infrastructure/db/models/__init__.py`:** This file is currently empty. The test conftest imports ORM modules directly (e.g., `from lore.infrastructure.db.models import chunk`). No changes to `__init__.py` are needed — adding the module to the conftest import is sufficient for `Base.metadata.create_all` to register the table.

- [ ] **Step 1: Write `RepositorySyncRunORM`**

```python
# lore/infrastructure/db/models/repository_sync_run.py
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class RepositorySyncRunORM(Base):
    __tablename__ = "repository_sync_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_repositories.id"), nullable=False
    )
    connector_id: Mapped[str] = mapped_column(nullable=False)
    trigger: Mapped[str] = mapped_column(nullable=False)
    mode: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_objects_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    documents_created: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    versions_created: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    versions_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    warnings: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 2: Add `repository_sync_run` to conftest model imports**

Open `tests/integration/conftest.py`. Find the block:

```python
from lore.infrastructure.db.models import (  # noqa: F401  # noqa: F401
    chunk,
    document,
    external_connection,
    external_object,
    external_repository,
    source,
)
```

Replace with:

```python
from lore.infrastructure.db.models import (  # noqa: F401  # noqa: F401
    chunk,
    document,
    external_connection,
    external_object,
    external_repository,
    repository_sync_run,
    source,
)
```

- [ ] **Step 3: Verify ORM imports without error**

```bash
python -c "from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM; print('ORM ok')"
```

Expected: `ORM ok`

- [ ] **Step 4: Commit**

```bash
git add lore/infrastructure/db/models/repository_sync_run.py tests/integration/conftest.py
git commit -m "feat(db): add RepositorySyncRunORM + register in test conftest"
```

---

## Task 3: `RepositorySyncRunRepository`

**Files:**
- Create: `lore/infrastructure/db/repositories/repository_sync_run.py`

- [ ] **Step 1: Write dataclass + repository**

```python
# lore/infrastructure/db/repositories/repository_sync_run.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.base import BaseRepository


@dataclass
class RepositorySyncRun:
    id: UUID
    repository_id: UUID
    connector_id: str
    trigger: str
    mode: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings: list[str]
    error_message: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _orm_to_schema(orm: RepositorySyncRunORM) -> RepositorySyncRun:
    return RepositorySyncRun(
        id=orm.id,
        repository_id=orm.repository_id,
        connector_id=orm.connector_id,
        trigger=orm.trigger,
        mode=orm.mode,
        status=orm.status,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
        raw_objects_processed=orm.raw_objects_processed,
        documents_created=orm.documents_created,
        versions_created=orm.versions_created,
        versions_skipped=orm.versions_skipped,
        warnings=[str(w) for w in orm.warnings],
        error_message=orm.error_message,
        metadata=dict(orm.metadata_),
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class RepositorySyncRunRepository(BaseRepository[RepositorySyncRunORM]):
    async def create_running(
        self,
        repository_id: UUID,
        connector_id: str,
        trigger: str,
        mode: str,
    ) -> RepositorySyncRun:
        now = datetime.now(UTC)
        orm = RepositorySyncRunORM(
            id=uuid4(),
            repository_id=repository_id,
            connector_id=connector_id,
            trigger=trigger,
            mode=mode,
            status="running",
            started_at=now,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)

    async def mark_finished(
        self,
        run_id: UUID,
        status: str,
        raw_objects_processed: int,
        documents_created: int,
        versions_created: int,
        versions_skipped: int,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> None:
        result = await self.session.execute(
            select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == run_id)
        )
        orm = result.scalar_one()
        orm.status = status
        orm.finished_at = datetime.now(UTC)
        orm.raw_objects_processed = raw_objects_processed
        orm.documents_created = documents_created
        orm.versions_created = versions_created
        orm.versions_skipped = versions_skipped
        orm.warnings = warnings
        orm.metadata_ = metadata
        await self.session.flush()

    async def mark_failed(self, run_id: UUID, error_message: str) -> None:
        result = await self.session.execute(
            select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == run_id)
        )
        orm = result.scalar_one()
        orm.status = "failed"
        orm.finished_at = datetime.now(UTC)
        orm.error_message = error_message
        # counters remain at 0 — no partial counter recovery
        await self.session.flush()

    async def list_by_repository(
        self,
        repository_id: UUID,
        limit: int = 50,
    ) -> list[RepositorySyncRun]:
        result = await self.session.execute(
            select(RepositorySyncRunORM)
            .where(RepositorySyncRunORM.repository_id == repository_id)
            .order_by(
                RepositorySyncRunORM.created_at.desc(),
                RepositorySyncRunORM.id.desc(),  # tiebreak for identical timestamps
            )
            .limit(limit)
        )
        return [_orm_to_schema(orm) for orm in result.scalars().all()]
```

- [ ] **Step 2: Verify imports**

```bash
python -c "from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository, RepositorySyncRun; print('repo ok')"
```

Expected: `repo ok`

- [ ] **Step 3: Commit**

```bash
git add lore/infrastructure/db/repositories/repository_sync_run.py
git commit -m "feat(db): add RepositorySyncRunRepository with create/mark methods"
```

---

## Task 4: Sync domain — errors, models, package

**Files:**
- Create: `lore/sync/__init__.py`
- Create: `lore/sync/errors.py`
- Create: `lore/sync/models.py`

- [ ] **Step 1: Create empty package marker**

```python
# lore/sync/__init__.py
```

(empty file)

- [ ] **Step 2: Write `lore/sync/errors.py`**

```python
# lore/sync/errors.py
from __future__ import annotations

from uuid import UUID


class RepositoryNotFoundError(Exception):
    def __init__(self, repository_id: UUID) -> None:
        super().__init__(f"Repository {repository_id} not found.")


class UnsupportedSyncModeError(Exception):
    def __init__(self, mode: str) -> None:
        super().__init__(
            f"Sync mode '{mode}' is not supported. Only 'full' is supported in this version."
        )
```

- [ ] **Step 3: Write `lore/sync/models.py`**

```python
# lore/sync/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


@dataclass
class RepositorySyncResult:
    sync_run_id: UUID
    repository_id: UUID
    status: str
    trigger: str
    mode: str
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Verify imports**

```bash
python -c "from lore.sync.errors import RepositoryNotFoundError, UnsupportedSyncModeError; from lore.sync.models import RepositorySyncResult; print('sync domain ok')"
```

Expected: `sync domain ok`

- [ ] **Step 5: Commit**

```bash
git add lore/sync/__init__.py lore/sync/errors.py lore/sync/models.py
git commit -m "feat(sync): add sync domain — errors and RepositorySyncResult model"
```

---

## Task 5: `RepositorySyncService`

**Files:**
- Create: `lore/sync/service.py`

- [ ] **Step 1: Write service**

```python
# lore/sync/service.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from lore.connector_sdk.models import FullSyncRequest
from lore.sync.errors import RepositoryNotFoundError, UnsupportedSyncModeError
from lore.sync.models import RepositorySyncResult

if TYPE_CHECKING:
    from lore.connector_sdk.registry import ConnectorRegistry
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
    ) -> None:
        self._registry = registry
        self._ingestion = ingestion
        self._ext_repo_repo = ext_repo_repo
        self._sync_run_repo = sync_run_repo

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
            report = await self._ingestion.ingest_sync_result(sync_result, connector)

            status = "partial" if report.warnings else "succeeded"

            await self._sync_run_repo.mark_finished(
                run_id=run.id,
                status=status,
                raw_objects_processed=report.raw_objects_processed,
                documents_created=report.documents_created,
                versions_created=report.versions_created,
                versions_skipped=report.versions_skipped,
                warnings=report.warnings,
                metadata={},
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
            # Known limitation: the route handler commits both mark_failed and any
            # partial ingestion flushes in one transaction. This is acceptable for
            # PR #3; a future PR may isolate sync_run persistence in its own transaction.
            raise
```

- [ ] **Step 2: Verify imports**

```bash
python -c "from lore.sync.service import RepositorySyncService; print('service ok')"
```

Expected: `service ok`

- [ ] **Step 3: Add TODO comment to `RepositoryImportService`**

Open `lore/ingestion/repository_import.py`. Find the line:

```python
        return ImportResult(
```

Just above it, add:

```python
        # TODO: record sync_run with trigger="import" once RepositoryImportService
        # is refactored to delegate ingestion to RepositorySyncService.
```

- [ ] **Step 4: Commit**

```bash
git add lore/sync/service.py lore/ingestion/repository_import.py
git commit -m "feat(sync): add RepositorySyncService — provider-agnostic sync lifecycle"
```

---

## Task 6: Integration Tests (write failing tests)

**Files:**
- Create: `tests/integration/connectors/test_sync_api.py`

**Design principle: each test is independent.** Each test generates a unique `owner_suffix` (8-char UUID slice) so it works with its own `external_repository` and `external_object` rows. Tests do not share state or rely on execution order. Provider ID `"fake-sync"` avoids collision with `"fake"` used in `test_import_api.py`.

The `_FakeSyncConnector` uses `owner_suffix` to generate stable-per-test identifiers (`external_id`, `external_url`, `logical_path`) so repeat syncs within the same test hit the same `Document` and `ExternalObject` rows — critical for idempotency tests C and D.

- [ ] **Step 1: Write the full test file**

```python
# tests/integration/connectors/test_sync_api.py
"""POST /api/v1/repositories/{id}/sync and GET /sync-runs — integration tests.

Each test is independent: uses a unique owner_suffix (uuid4 slice) to avoid
shared state between tests. No reliance on execution order.
Provider id "fake-sync" is distinct from "fake" used in test_import_api.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
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
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PROVIDER_ID = "fake-sync"


class _FakeSyncConnector(BaseConnector):
    """Fake connector for sync tests.

    owner_suffix makes provider/external_id/external_url unique per test.
    Within a single test, these identifiers stay stable across sync calls —
    only content and content_hash change — so repeat syncs hit the same
    Document and ExternalObject rows (required for idempotency tests C/D).
    """

    def __init__(
        self,
        owner_suffix: str = "default",
        content: str = "# Hello",
        raise_on_sync: Exception | None = None,
    ) -> None:
        self._suffix = owner_suffix
        self._content = content
        self._raise_on_sync = raise_on_sync

    # ── derived identifiers ───────────────────────────────────────────────────

    @property
    def _owner(self) -> str:
        return f"sync-org-{self._suffix}"

    @property
    def _repo(self) -> str:
        return f"sync-repo-{self._suffix}"

    @property
    def _full_name(self) -> str:
        return f"{self._owner}/{self._repo}"

    @property
    def _external_id(self) -> str:
        return f"{self._full_name}:file:README.md"

    @property
    def _external_url(self) -> str:
        return f"https://example.com/{self._full_name}/blob/abc/README.md"

    @property
    def _html_url(self) -> str:
        return f"https://example.com/{self._full_name}"

    # ── BaseConnector interface ───────────────────────────────────────────────

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id=PROVIDER_ID,
            display_name="Fake Sync",
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
            provider=PROVIDER_ID,
            owner=self._owner,
            name=self._repo,
            full_name=self._full_name,
            default_branch="main",
            html_url=self._html_url,
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        if self._raise_on_sync is not None:
            raise self._raise_on_sync

        payload = {"path": "README.md", "owner": self._owner, "repo": self._repo}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw = RawExternalObject(
            provider=PROVIDER_ID,
            object_type="github.file",
            external_id=self._external_id,
            external_url=self._external_url,
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
            content=self._content,
            content_hash="sha256:" + hashlib.sha256(self._content.encode()).hexdigest(),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={
                "commit_sha": "abc123",
                "path": "README.md",
                "owner": self._owner,
                "repo": self._repo,
                "branch": "main",
            },
        )
        return SyncResult(connector_id=PROVIDER_ID, raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        # Intentionally reuses GitHubNormalizer because fake-sync emits github.file-shaped objects.
        return GitHubNormalizer().normalize(raw)


# ── helpers ───────────────────────────────────────────────────────────────────


async def _import_repo(
    app: FastAPI,
    client: AsyncClient,
    owner_suffix: str,
    content: str = "# Hello",
) -> UUID:
    """Import a fresh repository with the given suffix. Returns repository_id."""
    connector = _FakeSyncConnector(owner_suffix=owner_suffix, content=content)
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(
        "/api/v1/repositories/import",
        json={"url": connector._html_url, "connector_id": PROVIDER_ID},
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()["repository_id"])


async def _sync(
    app: FastAPI,
    client: AsyncClient,
    repo_id: UUID,
    owner_suffix: str,
    content: str = "# Hello",
    failing: bool = False,
) -> tuple[int, dict]:
    """POST /sync for repo_id. Returns (status_code, body)."""
    registry = ConnectorRegistry()
    if failing:
        registry.register(
            _FakeSyncConnector(
                owner_suffix=owner_suffix,
                raise_on_sync=RuntimeError("connector boom"),
            )
        )
    else:
        registry.register(_FakeSyncConnector(owner_suffix=owner_suffix, content=content))
    app.state.connector_registry = registry
    resp = await client.post(f"/api/v1/repositories/{repo_id}/sync")
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


# ── A ─────────────────────────────────────────────────────────────────────────


async def test_a_sync_endpoint_returns_200(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """Sync an existing imported repo → 200, sync_run created, status=succeeded."""
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)
    status, body = await _sync(app_with_db, app_client_with_db, repo_id, owner_suffix=suffix)

    assert status == 200
    assert body["status"] == "succeeded"
    assert body["trigger"] == "manual"
    assert body["mode"] == "full"
    assert UUID(body["sync_run_id"])
    assert UUID(body["repository_id"]) == repo_id
    assert "raw_objects_processed" in body
    assert "documents_created" in body
    assert "versions_created" in body
    assert "versions_skipped" in body
    assert "warnings" in body


# ── B ─────────────────────────────────────────────────────────────────────────


async def test_b_sync_does_not_create_duplicate_repository(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Sync must not create a new external_repository row."""
    from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
    from sqlalchemy import func

    suffix = str(uuid4())[:8]

    # Import repo FIRST, then count — this is the baseline (import creates 1 row)
    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)

    count_before = (
        await db_session.execute(
            select(func.count()).select_from(ExternalRepositoryORM).where(
                ExternalRepositoryORM.id == repo_id
            )
        )
    ).scalar_one()
    assert count_before == 1  # sanity check

    await _sync(app_with_db, app_client_with_db, repo_id, owner_suffix=suffix)

    count_after = (
        await db_session.execute(
            select(func.count()).select_from(ExternalRepositoryORM).where(
                ExternalRepositoryORM.id == repo_id
            )
        )
    ).scalar_one()

    assert count_after == count_before  # sync must not add a row


# ── C ─────────────────────────────────────────────────────────────────────────


async def test_c_repeat_sync_same_content_no_new_versions(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """Re-syncing with identical content must not create a new document version."""
    suffix = str(uuid4())[:8]
    content = "# Version One"
    repo_id = await _import_repo(
        app_with_db, app_client_with_db, owner_suffix=suffix, content=content
    )

    # first sync — same content as import → no new version
    status1, body1 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content
    )
    assert status1 == 200, body1
    assert body1["versions_created"] == 0
    assert body1["versions_skipped"] >= 1

    # second sync — still same content → still no new version
    status2, body2 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content
    )
    assert status2 == 200, body2
    assert body2["versions_created"] == 0
    assert body2["versions_skipped"] >= 1


# ── D ─────────────────────────────────────────────────────────────────────────


async def test_d_sync_changed_content_creates_new_version(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """Syncing with changed content must create exactly one new document version."""
    suffix = str(uuid4())[:8]
    content_a = "# Version One"
    content_b = "# Version Two — changed"

    repo_id = await _import_repo(
        app_with_db, app_client_with_db, owner_suffix=suffix, content=content_a
    )

    # sync with same content — idempotent (version from import already exists)
    s0, b0 = await _sync(app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content_a)
    assert s0 == 200, b0

    # sync with changed content → new version
    status, body = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content_b
    )
    assert status == 200, body
    assert body["versions_created"] == 1


# ── E ─────────────────────────────────────────────────────────────────────────


async def test_e_failed_sync_marks_run_as_failed(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Connector failure → API returns 500, sync_run committed as failed with error_message."""
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)

    status, _ = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, failing=True
    )
    assert status == 500

    # route handler committed mark_failed before raising 500 — verify via DB
    result = await db_session.execute(
        select(RepositorySyncRunORM)
        .where(RepositorySyncRunORM.repository_id == repo_id)
        .where(RepositorySyncRunORM.status == "failed")
        .order_by(RepositorySyncRunORM.created_at.desc(), RepositorySyncRunORM.id.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    assert run is not None, "Expected a failed sync_run in DB after 500 response"
    assert run.error_message is not None
    assert "connector boom" in run.error_message


# ── F ─────────────────────────────────────────────────────────────────────────


async def test_f_list_sync_runs_newest_first(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """GET /sync-runs returns runs newest first, with all required fields."""
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)

    # create 2 syncs with different content so we get 2 distinct runs
    sf1, body1 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content="# Run F1"
    )
    assert sf1 == 200, body1
    sf2, body2 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content="# Run F2 — changed"
    )
    assert sf2 == 200, body2
    sync_run_id1 = body1["sync_run_id"]
    sync_run_id2 = body2["sync_run_id"]

    registry = ConnectorRegistry()
    registry.register(_FakeSyncConnector(owner_suffix=suffix))
    app_with_db.state.connector_registry = registry

    resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/sync-runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 2

    # newest first: body2's run must appear before body1's run
    run_ids = [r["id"] for r in runs]
    assert run_ids.index(sync_run_id2) < run_ids.index(sync_run_id1)

    # required fields present in every item
    first = runs[0]
    for field in (
        "id", "repository_id", "trigger", "mode", "status",
        "started_at", "finished_at", "raw_objects_processed",
        "documents_created", "versions_created", "versions_skipped",
        "warnings_count", "error_message",
    ):
        assert field in first, f"Missing field in sync-run list item: {field}"


# ── G ─────────────────────────────────────────────────────────────────────────


async def test_g_sync_nonexistent_repository_returns_404(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """POST /sync for an unknown UUID returns 404."""
    registry = ConnectorRegistry()
    registry.register(_FakeSyncConnector())
    app_with_db.state.connector_registry = registry

    resp = await app_client_with_db.post(f"/api/v1/repositories/{uuid4()}/sync")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests — expect them to fail (endpoints don't exist yet)**

```bash
python -m pytest tests/integration/connectors/test_sync_api.py -v --no-header -x 2>&1 | head -40
```

Expected: Tests fail — either import errors or `404 Not Found` on the sync endpoint. This is expected.

- [ ] **Step 3: Commit test file**

```bash
git add tests/integration/connectors/test_sync_api.py
git commit -m "test(sync): add integration tests A-G for sync lifecycle (failing — endpoints TBD)"
```

---

## Task 7: API Endpoints — make tests pass

**Files:**
- Modify: `apps/api/routes/v1/repositories.py`

Add schemas, DI builder, and two route handlers to the existing router. The route handler commits `mark_failed` state before raising a 500, so the test can verify the failed run via the DB.

- [ ] **Step 1: Add imports to `repositories.py`**

Open `apps/api/routes/v1/repositories.py`. After the existing imports block, add:

```python
from datetime import datetime

from fastapi import Query

from lore.connector_sdk.errors import ConnectorNotFoundError, ExternalResourceNotFoundError
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.sync.errors import RepositoryNotFoundError, UnsupportedSyncModeError
from lore.sync.service import RepositorySyncService
```

The full updated imports block for `repositories.py` should be:

```python
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TCH003

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from lore.connector_sdk.errors import ConnectorNotFoundError, ExternalResourceNotFoundError
from lore.infrastructure.db.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
)
from lore.infrastructure.db.repositories.external_connection import ExternalConnectionRepository
from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.infrastructure.db.session import get_session
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService
from lore.sync.errors import RepositoryNotFoundError, UnsupportedSyncModeError
from lore.sync.service import RepositorySyncService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from lore.connector_sdk.registry import ConnectorRegistry

router = APIRouter(prefix="/repositories", tags=["repositories"])

SessionDep = Annotated["AsyncSession", Depends(get_session)]
```

- [ ] **Step 2: Add Pydantic schemas**

After the existing `ImportResponse` class, add:

```python
class RepositorySyncResponse(BaseModel):
    sync_run_id: UUID
    repository_id: UUID
    status: str
    trigger: str
    mode: str
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings: list[str] = Field(default_factory=list)


class RepositorySyncRunListItem(BaseModel):
    id: UUID
    repository_id: UUID
    trigger: str
    mode: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings_count: int
    error_message: str | None
```

- [ ] **Step 3: Add DI builder for sync service**

After the existing `_build_import_service` function, add:

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
    return RepositorySyncService(registry, ingestion, ext_repo_repo, sync_run_repo)
```

- [ ] **Step 4: Add `POST /{repository_id}/sync` route**

After the existing `@router.get("/{repository_id}")` handler, add:

```python
@router.post("/{repository_id}/sync", response_model=RepositorySyncResponse)
async def sync_repository(
    repository_id: UUID,
    request: Request,
    session: SessionDep,
) -> RepositorySyncResponse:
    registry = request.app.state.connector_registry
    svc = _build_sync_service(session, registry)

    try:
        result = await svc.sync_repository(repository_id, trigger="manual", mode="full")
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnsupportedSyncModeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # mark_failed was flushed in the service — commit it so the run is persisted as failed
        await session.commit()
        raise HTTPException(status_code=500, detail="Sync failed") from exc

    await session.commit()

    return RepositorySyncResponse(
        sync_run_id=result.sync_run_id,
        repository_id=result.repository_id,
        status=result.status,
        trigger=result.trigger,
        mode=result.mode,
        raw_objects_processed=result.raw_objects_processed,
        documents_created=result.documents_created,
        versions_created=result.versions_created,
        versions_skipped=result.versions_skipped,
        warnings=result.warnings,
    )
```

- [ ] **Step 5: Add `GET /{repository_id}/sync-runs` route**

```python
@router.get(
    "/{repository_id}/sync-runs",
    response_model=list[RepositorySyncRunListItem],
)
async def list_sync_runs(
    repository_id: UUID,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[RepositorySyncRunListItem]:
    ext_repo_repo = ExternalRepositoryRepository(session)
    repo = await ext_repo_repo.get_by_id(repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    sync_run_repo = RepositorySyncRunRepository(session)
    runs = await sync_run_repo.list_by_repository(repository_id, limit=limit)

    return [
        RepositorySyncRunListItem(
            id=run.id,
            repository_id=run.repository_id,
            trigger=run.trigger,
            mode=run.mode,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            raw_objects_processed=run.raw_objects_processed,
            documents_created=run.documents_created,
            versions_created=run.versions_created,
            versions_skipped=run.versions_skipped,
            warnings_count=len(run.warnings),
            error_message=run.error_message,
        )
        for run in runs
    ]
```

- [ ] **Step 6: Run tests — expect all to pass**

```bash
python -m pytest tests/integration/connectors/test_sync_api.py -v --no-header 2>&1 | tail -20
```

Expected output (all green):
```
PASSED tests/integration/connectors/test_sync_api.py::test_a_sync_endpoint_returns_200
PASSED tests/integration/connectors/test_sync_api.py::test_b_sync_does_not_create_duplicate_repository
PASSED tests/integration/connectors/test_sync_api.py::test_c_repeat_sync_same_content_no_new_versions
PASSED tests/integration/connectors/test_sync_api.py::test_d_sync_changed_content_creates_new_version
PASSED tests/integration/connectors/test_sync_api.py::test_e_failed_sync_marks_run_as_failed
PASSED tests/integration/connectors/test_sync_api.py::test_f_list_sync_runs_newest_first
PASSED tests/integration/connectors/test_sync_api.py::test_g_sync_nonexistent_repository_returns_404
7 passed
```

If any test fails, diagnose the error and fix before committing.

- [ ] **Step 7: Commit**

```bash
git add apps/api/routes/v1/repositories.py
git commit -m "feat(api): add POST /sync and GET /sync-runs endpoints for repository sync lifecycle"
```

---

## Task 8: Final Verification

**Files:** No changes — verify all existing + new tests pass.

- [ ] **Step 1: Run full integration test suite**

```bash
python -m pytest tests/integration/ -v --no-header 2>&1 | tail -30
```

Expected: All tests pass including pre-existing `test_import_api.py`, `test_ingest_idempotency_db.py`, `test_repository_import_flow.py`.

- [ ] **Step 2: Run unit tests**

```bash
python -m pytest tests/unit/ -v --no-header 2>&1 | tail -20
```

Expected: All pass.

- [ ] **Step 3: Run linter**

```bash
make lint 2>&1 | tail -20
```

Expected: No errors.

- [ ] **Step 4: Run formatter**

```bash
make format 2>&1 | tail -10
```

If `make format` changes any files, review the diff and commit the formatting changes before proceeding.

- [ ] **Step 5: Run type checker**

```bash
make type-check 2>&1 | tail -30
```

Expected: No errors. If there are type errors in new files, fix them before committing.

Common mypy fixes for new files:
- Add `from __future__ import annotations` to all new Python files
- `Mapped[list[Any]]` requires `from typing import Any`
- `Mapped[str | None]` requires `from __future__ import annotations` or explicit `Optional[str]`

- [ ] **Step 6: Run all tests together**

```bash
make test 2>&1 | tail -20
```

Expected: All unit + integration + e2e pass.

- [ ] **Step 7: Final commit if any fixes were needed**

```bash
git add -p  # stage only the fix files
git commit -m "fix(sync): address lint/type-check issues in sync lifecycle"
```

---

## Self-Review Checklist (spec coverage)

| Spec section | Covered |
|---|---|
| `repository_sync_runs` table + indexes | Task 1 |
| `RepositorySyncRunORM` | Task 2 |
| `RepositorySyncRunRepository` (4 methods) | Task 3 |
| `lore/sync/` package | Task 4 |
| `RepositorySyncService` (provider-agnostic) | Task 5 |
| Tests A–G | Task 6 |
| `POST /repositories/{id}/sync` | Task 7 |
| `GET /repositories/{id}/sync-runs?limit` | Task 7 |
| `RepositorySyncResponse` schema | Task 7 |
| `RepositorySyncRunListItem` schema | Task 7 |
| `mark_failed` committed on 500 | Task 7 step 4 |
| `create_running` before try block | Task 5 |
| `RepositoryNotFoundError` → 404 | Task 7 |
| `ConnectorNotFoundError` → 404 | Task 7 |
| `UnsupportedSyncModeError` → 422 | Task 7 |
| Import integration left as TODO | Task 5 step 3 |
| No webhook/incremental/artifact code | All tasks |
| `warnings_count = len(run.warnings)` | Task 7 step 5 |
| `metadata_` attribute (not `metadata`) | Task 2, Task 3 |
| `updated_at` with `onupdate=func.now()` | Task 2 |
| `versions_skipped` in both responses | Task 7 |
| GET /sync-runs checks repo exists first | Task 7 step 5 |
