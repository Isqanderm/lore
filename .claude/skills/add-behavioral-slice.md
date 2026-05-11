# Add Behavioral Slice

Use when adding a new behavioral module to Lore (e.g. `graph/`, `memory/`, `context/`, or filling in a placeholder like `ingestion/`).

**Announce at start:** "Using add-behavioral-slice to implement [slice name]."

---

## What is a behavioral slice

A behavioral slice is an orchestration layer for one domain capability. It:
- Lives in `lore/<slice_name>/service.py`
- Works exclusively with **schema objects** (never ORM directly)
- Calls repositories for all data access
- Contains the intelligence: algorithms, business rules, coordination logic

## Strict boundaries

- **NEVER** import ORM models in a service — only import from `lore.schema.*` and `lore.infrastructure.db.repositories.*`
- **NEVER** add intelligence (ranking, fusion, scoring) to repositories
- **NEVER** define new data structures here — use or extend `lore/schema/`
- **NEVER** put business logic in `apps/api/` route handlers

---

## Process

### Step 1 — Understand the slice

Before writing code, answer:
- What inputs does the service accept? (schema objects, primitives)
- What does it return? (schema objects)
- Which repositories does it need?
- Is there domain logic that belongs in `lore/domain/` instead?

### Step 2 — Update schema if needed

If the slice needs new data types, add them to `lore/schema/` first:
```python
# lore/schema/<name>.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class NewEntity:
    id: UUID
    # fields...
    created_at: datetime
```

No SQLAlchemy. No behavior. Frozen dataclass only.

### Step 3 — Write the service skeleton with TDD

Write the failing test first:
```python
# tests/unit/<slice_name>/test_<slice_name>_service.py
import pytest
from lore.<slice_name>.service import <SliceName>Service

@pytest.mark.unit
async def test_<method_name>_<scenario>():
    service = <SliceName>Service(repository=FakeRepository())
    result = await service.<method_name>(...)
    assert result == expected
```

Then implement the minimal service:
```python
# lore/<slice_name>/service.py
from lore.infrastructure.db.repositories.<repo> import <Repo>Repository
from lore.schema.<entity> import <Entity>


class <SliceName>Service:
    def __init__(self, repository: <Repo>Repository) -> None:
        self._repository = repository

    async def <method_name>(self, ...) -> <Entity>:
        # orchestration logic here
        ...
```

### Step 4 — Wire into FastAPI (if needed)

Only if the slice needs an HTTP endpoint:
```python
# apps/api/routes/v1/<slice_name>.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.session import get_session
from lore.<slice_name>.service import <SliceName>Service

router = APIRouter(prefix="/<slice_name>", tags=["<slice_name>"])

@router.post("/")
async def create_<entity>(
    payload: <RequestModel>,
    session: AsyncSession = Depends(get_session),
) -> <ResponseModel>:
    service = <SliceName>Service(repository=<Repo>Repository(session))
    result = await service.<method>(...)
    return <ResponseModel>.model_validate(result.__dict__)
```

Mount in `apps/api/main.py`:
```python
from apps.api.routes.v1.<slice_name> import router as <slice_name>_router
v1_router.include_router(<slice_name>_router)
```

### Step 5 — Run tests and commit

```bash
make test-unit
make lint
make type-check
git add lore/<slice_name>/ tests/unit/<slice_name>/
git commit -m "feat: implement <slice_name> service — <what it does>"
```

---

## Checklist

- [ ] Schema types defined in `lore/schema/` (if new data needed)
- [ ] Service in `lore/<slice_name>/service.py` — no ORM imports
- [ ] Unit tests in `tests/unit/<slice_name>/`
- [ ] Integration tests if slice touches DB
- [ ] Route added to `apps/api/routes/v1/` (if HTTP needed)
- [ ] Router mounted in `apps/api/main.py`
- [ ] `make lint && make type-check` pass
- [ ] Committed

---

## Red flags

- Service imports anything from `lore.infrastructure.db.models.*` → STOP, use repository
- Repository method contains ranking or scoring logic → STOP, move to service
- Route handler contains business logic → STOP, move to service
- New dataclass defined inside `service.py` → STOP, put in `lore/schema/`
