# Write Tests

Use when writing tests for Lore — to choose the right level and follow project conventions.

**Announce at start:** "Using write-tests to add tests for [what]."

---

## Three levels — choose the right one

| Level | When to use | Fixture | Speed |
|---|---|---|---|
| `tests/unit/` | Pure logic: schema, domain, normalization, algorithms | None | Fast |
| `tests/integration/` | Repository contract, DB queries, Alembic-created tables | `db_session` (testcontainers) | Slow |
| `tests/e2e/` | Full HTTP cycle via FastAPI | `test_client` (TestClient) | Medium |

**Rule:** test at the lowest level that actually verifies the behavior. Unit test for domain logic. Integration test for DB queries. E2E only for the API contract.

---

## Unit tests

```python
# tests/unit/<module>/test_<thing>.py
import pytest
from lore.<module>.<file> import <function_or_class>

@pytest.mark.unit
def test_<behavior>_when_<condition>() -> None:
    result = <function_or_class>(input)
    assert result == expected

@pytest.mark.unit
def test_<behavior>_raises_when_<condition>() -> None:
    with pytest.raises(<ErrorType>):
        <function_or_class>(bad_input)
```

No DB. No mocks of internal Lore code. If you need to mock, it means the unit is too large.

---

## Integration tests

```python
# tests/integration/test_<entity>_repository.py
import pytest
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.repositories.<entity> import <Entity>Repository
from lore.schema.<entity> import <Entity>

@pytest.mark.integration
async def test_create_and_get(db_session: AsyncSession) -> None:
    repo = <Entity>Repository(db_session)
    entity = <Entity>(id=uuid4(), ..., created_at=datetime.now(tz=timezone.utc))

    created = await repo.create(entity)
    assert created.id == entity.id

    fetched = await repo.get_by_id(entity.id)
    assert fetched is not None
    assert fetched.id == entity.id

@pytest.mark.integration
async def test_get_by_id_returns_none_when_missing(db_session: AsyncSession) -> None:
    repo = <Entity>Repository(db_session)
    result = await repo.get_by_id(uuid4())
    assert result is None
```

The `db_session` fixture (in `tests/integration/conftest.py`) runs `session.rollback()` after each test — data doesn't accumulate. Use `datetime.now(tz=timezone.utc)` for timestamps (asyncpg requires timezone-aware datetimes).

---

## E2E tests

```python
# tests/e2e/test_<endpoint>.py
import pytest
from fastapi.testclient import TestClient

@pytest.mark.e2e
def test_<endpoint>_returns_<expected>(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/<path>")
    assert response.status_code == 200
    assert response.json() == {"key": "value"}

@pytest.mark.e2e
def test_<endpoint>_returns_error_when_<condition>(test_client: TestClient) -> None:
    response = test_client.post("/api/v1/<path>", json={"bad": "data"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
```

The `test_client` fixture is in `tests/e2e/conftest.py`. It uses `create_app()` — the full application factory.

---

## Async fixtures

Use `pytest_asyncio.fixture` for async fixtures, plain `pytest.fixture` for sync:

```python
import pytest
import pytest_asyncio

@pytest.fixture
def sync_thing() -> SyncThing:
    return SyncThing()

@pytest_asyncio.fixture
async def async_thing() -> AsyncThing:
    thing = await AsyncThing.create()
    yield thing
    await thing.cleanup()
```

---

## Conventions

- Test name: `test_<what>_<when_condition>` — readable without opening the file
- One assertion group per test — don't mix unrelated assertions
- `@pytest.mark.unit` / `@pytest.mark.integration` / `@pytest.mark.e2e` on every test
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed on individual tests
- `datetime.now(tz=timezone.utc)` — always timezone-aware for DB timestamps

---

## Running

```bash
make test-unit         # fast, no Docker needed
make test-integration  # needs Docker daemon running
make test-e2e          # medium speed
make test              # all three
```
