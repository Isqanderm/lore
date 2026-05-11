# Add Repository

Use when adding a new ORM model, schema type, and repository to Lore's data layer.

**Announce at start:** "Using add-repository to add [entity name]."

---

## Architecture reminder

```
lore/schema/<entity>.py                   ← frozen dataclass, NO SQLAlchemy
lore/infrastructure/db/models/<entity>.py ← ORM model only
lore/infrastructure/db/repositories/<entity>.py ← IO primitives only
migrations/versions/<id>_add_<entity>.py ← Alembic migration
tests/integration/test_<entity>_repository.py ← real DB test
```

These four files always travel together.

---

## Step-by-step

### Step 1 — Schema type (if not exists)

```python
# lore/schema/<entity>.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class <Entity>:
    id: UUID
    # --- add fields ---
    created_at: datetime
```

Rules:
- `frozen=True` always
- No SQLAlchemy imports ever
- No methods with business logic

### Step 2 — Write the failing integration test

```python
# tests/integration/test_<entity>_repository.py
import pytest
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.repositories.<entity> import <Entity>Repository
from lore.schema.<entity> import <Entity>

@pytest.mark.integration
async def test_create_and_get_<entity>(db_session: AsyncSession) -> None:
    repo = <Entity>Repository(db_session)
    entity = <Entity>(
        id=uuid4(),
        # fields...
        created_at=datetime.now(tz=timezone.utc),
    )
    created = await repo.create(entity)
    assert created.id == entity.id

    fetched = await repo.get_by_id(entity.id)
    assert fetched is not None
    assert fetched.id == entity.id
```

Run it: `make test-integration` — should FAIL (table doesn't exist yet).

### Step 3 — ORM model

```python
# lore/infrastructure/db/models/<entity>.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class <Entity>ORM(Base):
    __tablename__ = "<entities>"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # add foreign keys:
    # related_id: Mapped[UUID] = mapped_column(ForeignKey("related.id"), nullable=False, index=True)
    # add fields...
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
```

Import the model in `lore/infrastructure/db/models/__init__.py` so Alembic can discover it.

### Step 4 — Repository

```python
# lore/infrastructure/db/repositories/<entity>.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

from sqlalchemy import select

from lore.infrastructure.db.models.<entity> import <Entity>ORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.<entity> import <Entity>


def _orm_to_schema(orm: <Entity>ORM) -> <Entity>:
    return <Entity>(
        id=orm.id,
        # map fields...
        created_at=orm.created_at,
    )


class <Entity>Repository(BaseRepository[<Entity>ORM]):
    async def create(self, entity: <Entity>) -> <Entity>:
        orm = <Entity>ORM(
            id=entity.id,
            # map fields...
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> <Entity> | None:
        result = await self.session.execute(
            select(<Entity>ORM).where(<Entity>ORM.id == id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
```

**Repository rules:**
- Accepts schema objects, returns schema objects — never ORM objects
- `_orm_to_schema()` is always private and lives in this file
- No ranking, no scoring, no fusion — dumb IO only
- Additional read methods: `list_by_<field>`, `exists`, `count` — fine
- Never add `hybrid_search` or reranking here

### Step 5 — Alembic migration

```bash
make migration name=add_<entity>
```

Edit the generated file:
```python
# migrations/versions/<id>_add_<entity>.py
import sqlalchemy as sa
from alembic import op

def upgrade() -> None:
    op.create_table(
        "<entities>",
        sa.Column("id", sa.UUID(), nullable=False),
        # add FK: sa.Column("related_id", sa.UUID(), nullable=False),
        # add fields...
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        # add FK constraint: sa.ForeignKeyConstraint(["related_id"], ["related.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_<entities>_<field>", "<entities>", ["<field>"])

def downgrade() -> None:
    op.drop_table("<entities>")
```

### Step 6 — Run the test (should pass now)

The integration test uses `Base.metadata.create_all` via testcontainers — it picks up the new ORM model automatically. Run:

```bash
make test-integration
```

Expected: all green.

### Step 7 — Commit

```bash
git add lore/schema/<entity>.py \
        lore/infrastructure/db/models/<entity>.py \
        lore/infrastructure/db/repositories/<entity>.py \
        migrations/versions/<id>_add_<entity>.py \
        tests/integration/test_<entity>_repository.py
git commit -m "feat: add <Entity> schema, ORM model, repository, and migration"
```

---

## Checklist

- [ ] `lore/schema/<entity>.py` — frozen dataclass, no SQLAlchemy
- [ ] `lore/infrastructure/db/models/<entity>.py` — ORM model
- [ ] Model imported in `lore/infrastructure/db/models/__init__.py`
- [ ] `lore/infrastructure/db/repositories/<entity>.py` — IO primitives only
- [ ] `migrations/versions/<id>_add_<entity>.py` — Alembic migration
- [ ] `tests/integration/test_<entity>_repository.py` — create + get_by_id at minimum
- [ ] `make test-integration` passes
- [ ] `make lint && make type-check` pass
- [ ] Committed

---

## Red flags

- ORM model imports from `lore.schema.*` → wrong direction, don't do it
- Repository returns ORM object instead of schema object → fix `_orm_to_schema`
- Repository method contains business logic → move to service
- Migration creates a PostgreSQL ENUM for SourceType-like fields → use TEXT instead
