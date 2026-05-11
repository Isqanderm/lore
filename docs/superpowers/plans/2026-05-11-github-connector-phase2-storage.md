# GitHub Connector Foundation — Phase 2: Storage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the integration layer tables, update existing tables, add ORM models, and extend repositories.

**Architecture:** Migration 0002 adds 3 new tables and nullable columns to existing tables. ORM models follow the existing pattern in `lore/infrastructure/db/models/`. Repositories follow `BaseRepository[T]` pattern.

**Tech Stack:** SQLAlchemy 2.0 async ORM, Alembic, PostgreSQL JSONB, asyncpg

**Prerequisites:** Phase 1 (Connector SDK) complete.

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Create | `migrations/versions/0002_integration_layer.py` | DB schema for integration layer |
| Create | `lore/infrastructure/db/models/external_connection.py` | ExternalConnectionORM |
| Create | `lore/infrastructure/db/models/external_repository.py` | ExternalRepositoryORM |
| Create | `lore/infrastructure/db/models/external_object.py` | ExternalObjectORM |
| Modify | `lore/infrastructure/db/models/source.py` | add external_object_id FK |
| Modify | `lore/infrastructure/db/models/document.py` | add document_kind, logical_path, metadata |
| Modify | `lore/schema/source.py` | add external_object_id field |
| Modify | `lore/schema/document.py` | add document_kind, logical_path, metadata; version_ref, source_updated_at, metadata |
| Create | `lore/infrastructure/db/repositories/external_connection.py` | ExternalConnectionRepository |
| Create | `lore/infrastructure/db/repositories/external_repository.py` | ExternalRepositoryRepository |
| Create | `lore/infrastructure/db/repositories/external_object.py` | ExternalObjectRepository |
| Modify | `lore/infrastructure/db/repositories/source.py` | add get_by_external_object_id |
| Modify | `lore/infrastructure/db/repositories/document.py` | add get_by_source_kind_path, get_latest_version |
| Modify | `tests/integration/conftest.py` | add new model imports |
| Create | `tests/unit/test_orm_external_models.py` | ORM smoke tests |

---

## Task 4: Migration 0002 — Integration Layer

**Files:**
- Create: `migrations/versions/0002_integration_layer.py`

- [ ] **Step 1: Write a failing integration test that checks tables exist**

```python
# tests/integration/test_migration_0002.py
import pytest
import sqlalchemy


@pytest.mark.integration
async def test_external_connections_table_exists(db_engine):
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='external_connections'"
            )
        )
        assert result.scalar() == "external_connections"


@pytest.mark.integration
async def test_external_repositories_table_exists(db_engine):
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='external_repositories'"
            )
        )
        assert result.scalar() == "external_repositories"


@pytest.mark.integration
async def test_external_objects_unique_constraint(db_engine):
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name='external_objects' "
                "AND constraint_type='UNIQUE' "
                "AND constraint_name='uq_external_objects_connection_provider_id'"
            )
        )
        assert result.scalar() is not None


@pytest.mark.integration
async def test_sources_has_external_object_id_column(db_engine):
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='sources' AND column_name='external_object_id'"
            )
        )
        assert result.scalar() == "external_object_id"


@pytest.mark.integration
async def test_document_versions_has_version_ref(db_engine):
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='document_versions' AND column_name='version_ref'"
            )
        )
        assert result.scalar() == "version_ref"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/integration/test_migration_0002.py -v -m integration
```
Expected: all FAILED — tables do not exist yet

- [ ] **Step 3: Write migration 0002**

```python
# migrations/versions/0002_integration_layer.py
"""integration layer — external_connections, external_repositories, external_objects

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("external_account_id", sa.Text(), nullable=True),
        sa.Column("installation_id", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "external_repositories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["connection_id"], ["external_connections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_repositories_provider_full_name",
        "external_repositories",
        ["provider", "full_name"],
    )

    op.create_table(
        "external_objects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=True),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column(
            "raw_payload_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("raw_payload_hash", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["external_connections.id"]),
        sa.ForeignKeyConstraint(["repository_id"], ["external_repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider",
            "external_id",
            name="uq_external_objects_connection_provider_id",
        ),
    )
    op.create_index(
        "ix_external_objects_repository_id",
        "external_objects",
        ["repository_id"],
    )
    op.create_index(
        "ix_external_objects_provider_object_type",
        "external_objects",
        ["provider", "object_type"],
    )

    # Evolve existing tables (all nullable — no breaking change)
    op.add_column(
        "sources",
        sa.Column("external_object_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sources_external_object_id",
        "sources",
        "external_objects",
        ["external_object_id"],
        ["id"],
    )
    op.create_index("ix_sources_external_object_id", "sources", ["external_object_id"])

    op.add_column("documents", sa.Column("document_kind", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("logical_path", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_documents_document_kind", "documents", ["document_kind"])
    op.create_index("ix_documents_logical_path", "documents", ["logical_path"])

    op.add_column("document_versions", sa.Column("version_ref", sa.Text(), nullable=True))
    op.add_column(
        "document_versions",
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_document_versions_content_hash", "document_versions", ["checksum"]
    )
    op.create_index(
        "ix_document_versions_version_ref", "document_versions", ["version_ref"]
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_version_ref", "document_versions")
    op.drop_index("ix_document_versions_content_hash", "document_versions")
    op.drop_column("document_versions", "metadata")
    op.drop_column("document_versions", "source_updated_at")
    op.drop_column("document_versions", "version_ref")

    op.drop_index("ix_documents_logical_path", "documents")
    op.drop_index("ix_documents_document_kind", "documents")
    op.drop_column("documents", "metadata")
    op.drop_column("documents", "logical_path")
    op.drop_column("documents", "document_kind")

    op.drop_index("ix_sources_external_object_id", "sources")
    op.drop_constraint("fk_sources_external_object_id", "sources", type_="foreignkey")
    op.drop_column("sources", "external_object_id")

    op.drop_index("ix_external_objects_provider_object_type", "external_objects")
    op.drop_index("ix_external_objects_repository_id", "external_objects")
    op.drop_table("external_objects")
    op.drop_index("ix_external_repositories_provider_full_name", "external_repositories")
    op.drop_table("external_repositories")
    op.drop_table("external_connections")
```

- [ ] **Step 4: Update integration conftest to import new models**

Add to `tests/integration/conftest.py` imports line (the existing `from lore.infrastructure.db.models import chunk, document, source  # noqa: F401`):

```python
from lore.infrastructure.db.models import chunk, document, external_connection, external_object, external_repository, source  # noqa: F401
```

Note: the ORM models must exist before this import works (created in Task 5).

- [ ] **Step 5: Run integration migration tests**

```
pytest tests/integration/test_migration_0002.py -v -m integration
```
Expected: all PASSED (migration runs via `Base.metadata.create_all` in conftest, but we also need the migration to be used by Alembic)

- [ ] **Step 6: Commit migration**

```bash
git add migrations/versions/0002_integration_layer.py tests/integration/test_migration_0002.py
git commit -m "feat(db): migration 0002 — integration layer tables and existing table evolution"
```

---

## Task 5: New ORM models

**Files:**
- Create: `lore/infrastructure/db/models/external_connection.py`
- Create: `lore/infrastructure/db/models/external_repository.py`
- Create: `lore/infrastructure/db/models/external_object.py`
- Create: `tests/unit/test_orm_external_models.py`

- [ ] **Step 1: Write ORM smoke tests**

```python
# tests/unit/test_orm_external_models.py
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM


def test_external_connection_table_name() -> None:
    assert ExternalConnectionORM.__tablename__ == "external_connections"


def test_external_repository_table_name() -> None:
    assert ExternalRepositoryORM.__tablename__ == "external_repositories"


def test_external_object_table_name() -> None:
    assert ExternalObjectORM.__tablename__ == "external_objects"


def test_external_object_unique_constraint() -> None:
    constraint_names = {c.name for c in ExternalObjectORM.__table__.constraints}
    assert "uq_external_objects_connection_provider_id" in constraint_names


def test_external_object_has_required_columns() -> None:
    cols = {c.name for c in ExternalObjectORM.__table__.columns}
    assert {"provider", "object_type", "external_id", "raw_payload_json",
            "raw_payload_hash", "content_hash", "fetched_at"}.issubset(cols)
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/test_orm_external_models.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement ExternalConnectionORM**

```python
# lore/infrastructure/db/models/external_connection.py
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ExternalConnectionORM(Base):
    __tablename__ = "external_connections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(nullable=False)
    auth_mode: Mapped[str] = mapped_column(nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(nullable=True)
    installation_id: Mapped[str | None] = mapped_column(nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 4: Implement ExternalRepositoryORM**

```python
# lore/infrastructure/db/models/external_repository.py
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ExternalRepositoryORM(Base):
    __tablename__ = "external_repositories"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_connections.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(nullable=False)
    owner: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str] = mapped_column(nullable=False)
    default_branch: Mapped[str] = mapped_column(nullable=False)
    html_url: Mapped[str] = mapped_column(nullable=False)
    visibility: Mapped[str | None] = mapped_column(nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 5: Implement ExternalObjectORM**

```python
# lore/infrastructure/db/models/external_object.py
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ExternalObjectORM(Base):
    __tablename__ = "external_objects"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "provider",
            "external_id",
            name="uq_external_objects_connection_provider_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_repositories.id"), nullable=True, index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_connections.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(nullable=False)
    object_type: Mapped[str] = mapped_column(nullable=False)
    external_id: Mapped[str] = mapped_column(nullable=False)
    external_url: Mapped[str | None] = mapped_column(nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    raw_payload_hash: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str | None] = mapped_column(nullable=True)
    content_hash: Mapped[str | None] = mapped_column(nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(nullable=False)
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
```

- [ ] **Step 6: Run unit tests**

```
pytest tests/unit/test_orm_external_models.py -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add lore/infrastructure/db/models/external_connection.py lore/infrastructure/db/models/external_repository.py lore/infrastructure/db/models/external_object.py tests/unit/test_orm_external_models.py
git commit -m "feat(db): ExternalConnection, ExternalRepository, ExternalObject ORM models"
```

---

## Task 6: Update existing ORM models + schema dataclasses

**Files:**
- Modify: `lore/infrastructure/db/models/source.py`
- Modify: `lore/infrastructure/db/models/document.py`
- Modify: `lore/schema/source.py`
- Modify: `lore/schema/document.py`

- [ ] **Step 1: Update SourceORM (add external_object_id)**

```python
# lore/infrastructure/db/models/source.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class SourceORM(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_type_raw: Mapped[str] = mapped_column(nullable=False)
    source_type_canonical: Mapped[str] = mapped_column(nullable=False, index=True)
    origin: Mapped[str] = mapped_column(nullable=False)
    external_object_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_objects.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 2: Update DocumentORM (add document_kind, logical_path, metadata)**

```python
# lore/infrastructure/db/models/document.py
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(nullable=False)
    path: Mapped[str] = mapped_column(nullable=False)
    document_kind: Mapped[str | None] = mapped_column(nullable=True, index=True)
    logical_path: Mapped[str | None] = mapped_column(nullable=True, index=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentVersionORM(Base):
    __tablename__ = "document_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(nullable=False, index=True)
    version_ref: Mapped[str | None] = mapped_column(nullable=True, index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
```

- [ ] **Step 3: Update lore/schema/source.py**

```python
# lore/schema/source.py
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SourceType(StrEnum):
    GIT_REPO = "git_repo"
    MARKDOWN = "markdown"
    ADR = "adr"
    SLACK = "slack"
    CONFLUENCE = "confluence"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Source:
    id: UUID
    source_type_raw: str
    source_type_canonical: SourceType
    origin: str
    created_at: datetime
    updated_at: datetime
    external_object_id: UUID | None = None
```

- [ ] **Step 4: Update lore/schema/document.py**

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

- [ ] **Step 5: Run existing unit tests to confirm no regressions**

```
pytest tests/unit/ -v
```
Expected: all PASSED (new fields have defaults, frozen tests still work)

- [ ] **Step 6: Commit**

```bash
git add lore/infrastructure/db/models/source.py lore/infrastructure/db/models/document.py lore/schema/source.py lore/schema/document.py
git commit -m "feat(schema,orm): add connector-layer fields to Source, Document, DocumentVersion"
```

---

## Task 7: Repositories — External* + updates to existing

**Files:**
- Create: `lore/infrastructure/db/repositories/external_connection.py`
- Create: `lore/infrastructure/db/repositories/external_repository.py`
- Create: `lore/infrastructure/db/repositories/external_object.py`
- Modify: `lore/infrastructure/db/repositories/source.py`
- Modify: `lore/infrastructure/db/repositories/document.py`
- Modify: `tests/integration/conftest.py`

- [ ] **Step 1: Implement ExternalConnectionRepository**

```python
# lore/infrastructure/db/repositories/external_connection.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.repositories.base import BaseRepository


@dataclass
class ExternalConnection:
    id: UUID
    provider: str
    auth_mode: str
    external_account_id: str | None
    installation_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _orm_to_schema(orm: ExternalConnectionORM) -> ExternalConnection:
    return ExternalConnection(
        id=orm.id,
        provider=orm.provider,
        auth_mode=orm.auth_mode,
        external_account_id=orm.external_account_id,
        installation_id=orm.installation_id,
        metadata=orm.metadata,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class ExternalConnectionRepository(BaseRepository[ExternalConnectionORM]):
    async def get_or_create_env_pat(self, provider: str) -> ExternalConnection:
        """Get the env-PAT connection for a provider, or create one."""
        result = await self.session.execute(
            select(ExternalConnectionORM).where(
                ExternalConnectionORM.provider == provider,
                ExternalConnectionORM.auth_mode == "env_pat",
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = ExternalConnectionORM(
                id=uuid4(),
                provider=provider,
                auth_mode="env_pat",
                external_account_id=None,
                installation_id=None,
                metadata={"token_source": "env", "configured": True},
            )
            self.session.add(orm)
            await self.session.flush()
        return _orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> ExternalConnection | None:
        result = await self.session.execute(
            select(ExternalConnectionORM).where(ExternalConnectionORM.id == id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
```

- [ ] **Step 2: Implement ExternalRepositoryRepository**

```python
# lore/infrastructure/db/repositories/external_repository.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.connector_sdk.models import ExternalContainerDraft


@dataclass
class ExternalRepository:
    id: UUID
    connection_id: UUID
    provider: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    html_url: str
    visibility: str | None
    last_synced_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _orm_to_schema(orm: ExternalRepositoryORM) -> ExternalRepository:
    return ExternalRepository(
        id=orm.id,
        connection_id=orm.connection_id,
        provider=orm.provider,
        owner=orm.owner,
        name=orm.name,
        full_name=orm.full_name,
        default_branch=orm.default_branch,
        html_url=orm.html_url,
        visibility=orm.visibility,
        last_synced_at=orm.last_synced_at,
        metadata=orm.metadata,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class ExternalRepositoryRepository(BaseRepository[ExternalRepositoryORM]):
    async def get_or_create(
        self,
        connection_id: UUID,
        draft: ExternalContainerDraft,
    ) -> ExternalRepository:
        result = await self.session.execute(
            select(ExternalRepositoryORM).where(
                ExternalRepositoryORM.connection_id == connection_id,
                ExternalRepositoryORM.provider == draft.provider,
                ExternalRepositoryORM.full_name == draft.full_name,
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = ExternalRepositoryORM(
                id=uuid4(),
                connection_id=connection_id,
                provider=draft.provider,
                owner=draft.owner,
                name=draft.name,
                full_name=draft.full_name,
                default_branch=draft.default_branch,
                html_url=draft.html_url,
                visibility=draft.visibility,
                last_synced_at=None,
                metadata=draft.metadata,
            )
            self.session.add(orm)
            await self.session.flush()
        return _orm_to_schema(orm)

    async def mark_synced(self, id: UUID, synced_at: datetime) -> None:
        result = await self.session.execute(
            select(ExternalRepositoryORM).where(ExternalRepositoryORM.id == id)
        )
        orm = result.scalar_one()
        orm.last_synced_at = synced_at
        await self.session.flush()

    async def get_by_id(self, id: UUID) -> ExternalRepository | None:
        result = await self.session.execute(
            select(ExternalRepositoryORM).where(ExternalRepositoryORM.id == id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
```

- [ ] **Step 3: Implement ExternalObjectRepository**

```python
# lore/infrastructure/db/repositories/external_object.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert

from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.connector_sdk.models import RawExternalObject


@dataclass
class ExternalObject:
    id: UUID
    repository_id: UUID | None
    connection_id: UUID
    provider: str
    object_type: str
    external_id: str
    external_url: str | None
    raw_payload_json: dict[str, Any]
    raw_payload_hash: str
    content: str | None
    content_hash: str | None
    source_updated_at: datetime | None
    fetched_at: datetime
    metadata: dict[str, Any]


class ExternalObjectRepository(BaseRepository[ExternalObjectORM]):
    async def upsert(self, raw: RawExternalObject) -> ExternalObject:
        """Upsert by (connection_id, provider, external_id). Returns the persisted record."""
        stmt = (
            insert(ExternalObjectORM)
            .values(
                id=uuid4(),
                repository_id=raw.repository_id,
                connection_id=raw.connection_id,
                provider=raw.provider,
                object_type=raw.object_type,
                external_id=raw.external_id,
                external_url=raw.external_url,
                raw_payload_json=raw.raw_payload,
                raw_payload_hash=raw.raw_payload_hash,
                content=raw.content,
                content_hash=raw.content_hash,
                source_updated_at=raw.source_updated_at,
                fetched_at=raw.fetched_at,
                metadata=raw.metadata,
            )
            .on_conflict_do_update(
                constraint="uq_external_objects_connection_provider_id",
                set_={
                    "repository_id": raw.repository_id,
                    "object_type": raw.object_type,
                    "external_url": raw.external_url,
                    "raw_payload_json": raw.raw_payload,
                    "raw_payload_hash": raw.raw_payload_hash,
                    "content": raw.content,
                    "content_hash": raw.content_hash,
                    "source_updated_at": raw.source_updated_at,
                    "fetched_at": raw.fetched_at,
                    "metadata": raw.metadata,
                },
            )
            .returning(ExternalObjectORM)
        )
        result = await self.session.execute(stmt)
        orm = result.scalar_one()
        return ExternalObject(
            id=orm.id,
            repository_id=orm.repository_id,
            connection_id=orm.connection_id,
            provider=orm.provider,
            object_type=orm.object_type,
            external_id=orm.external_id,
            external_url=orm.external_url,
            raw_payload_json=orm.raw_payload_json,
            raw_payload_hash=orm.raw_payload_hash,
            content=orm.content,
            content_hash=orm.content_hash,
            source_updated_at=orm.source_updated_at,
            fetched_at=orm.fetched_at,
            metadata=orm.metadata,
        )
```

- [ ] **Step 4: Update SourceRepository — add get_by_external_object_id**

Add to `lore/infrastructure/db/repositories/source.py`:

```python
    async def get_by_external_object_id(self, external_object_id: UUID) -> Source | None:
        result = await self.session.execute(
            select(SourceORM).where(SourceORM.external_object_id == external_object_id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None

    async def create_with_external_object(
        self,
        source: Source,
        external_object_id: UUID,
    ) -> Source:
        orm = SourceORM(
            id=source.id,
            source_type_raw=source.source_type_raw,
            source_type_canonical=source.source_type_canonical.value,
            origin=source.origin,
            external_object_id=external_object_id,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)
```

Also update `_orm_to_schema` in source.py to include `external_object_id`:

```python
def _orm_to_schema(orm: SourceORM) -> Source:
    return Source(
        id=orm.id,
        source_type_raw=orm.source_type_raw,
        source_type_canonical=SourceType(orm.source_type_canonical),
        origin=orm.origin,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        external_object_id=orm.external_object_id,
    )
```

- [ ] **Step 5: Update DocumentRepository and DocumentVersionRepository**

Add to `lore/infrastructure/db/repositories/document.py`:

```python
from sqlalchemy import desc, select

# add to _doc_orm_to_schema:
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
        metadata=orm.metadata,
    )

# add to _dv_orm_to_schema:
def _dv_orm_to_schema(orm: DocumentVersionORM) -> DocumentVersion:
    return DocumentVersion(
        id=orm.id,
        document_id=orm.document_id,
        version=orm.version,
        content=orm.content,
        checksum=orm.checksum,
        created_at=orm.created_at,
        version_ref=orm.version_ref,
        source_updated_at=orm.source_updated_at,
        metadata=orm.metadata,
    )

# add to DocumentRepository class:
    async def get_by_source_kind_path(
        self,
        source_id: UUID,
        document_kind: str,
        logical_path: str,
    ) -> Document | None:
        result = await self.session.execute(
            select(DocumentORM).where(
                DocumentORM.source_id == source_id,
                DocumentORM.document_kind == document_kind,
                DocumentORM.logical_path == logical_path,
            )
        )
        orm = result.scalar_one_or_none()
        return _doc_orm_to_schema(orm) if orm else None

# add to DocumentVersionRepository class:
    async def get_latest_version(self, document_id: UUID) -> DocumentVersion | None:
        result = await self.session.execute(
            select(DocumentVersionORM)
            .where(DocumentVersionORM.document_id == document_id)
            .order_by(desc(DocumentVersionORM.version))
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        return _dv_orm_to_schema(orm) if orm else None

    async def get_max_version(self, document_id: UUID) -> int:
        from sqlalchemy import func as sqlfunc
        result = await self.session.execute(
            select(sqlfunc.max(DocumentVersionORM.version)).where(
                DocumentVersionORM.document_id == document_id
            )
        )
        return result.scalar_one_or_none() or 0
```

Also update `DocumentRepository.create` to pass new fields:

```python
    async def create(self, doc: Document) -> Document:
        orm = DocumentORM(
            id=doc.id,
            source_id=doc.source_id,
            title=doc.title,
            path=doc.path,
            document_kind=doc.document_kind,
            logical_path=doc.logical_path,
            metadata=doc.metadata,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _doc_orm_to_schema(orm)
```

And `DocumentVersionRepository.create`:

```python
    async def create(self, dv: DocumentVersion) -> DocumentVersion:
        orm = DocumentVersionORM(
            id=dv.id,
            document_id=dv.document_id,
            version=dv.version,
            content=dv.content,
            checksum=dv.checksum,
            version_ref=dv.version_ref,
            source_updated_at=dv.source_updated_at,
            metadata=dv.metadata,
            created_at=dv.created_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _dv_orm_to_schema(orm)
```

- [ ] **Step 6: Update integration conftest imports**

In `tests/integration/conftest.py`, update the model import line to:

```python
from lore.infrastructure.db.models import (  # noqa: F401
    chunk,
    document,
    external_connection,
    external_object,
    external_repository,
    source,
)
```

- [ ] **Step 7: Run full test suite**

```
pytest tests/unit/ -v
pytest tests/integration/ -v -m integration
```
Expected: all PASSED

- [ ] **Step 8: Commit**

```bash
git add \
  lore/infrastructure/db/repositories/external_connection.py \
  lore/infrastructure/db/repositories/external_repository.py \
  lore/infrastructure/db/repositories/external_object.py \
  lore/infrastructure/db/repositories/source.py \
  lore/infrastructure/db/repositories/document.py \
  tests/integration/conftest.py
git commit -m "feat(db): External* repositories + update Source/Document repositories"
```

---

## Phase 2 complete

Storage layer is complete: migration, ORM models, repositories all in place. Proceed to Phase 3: GitHub Connector.

Next plan file: `2026-05-11-github-connector-phase3-github-connector.md`
