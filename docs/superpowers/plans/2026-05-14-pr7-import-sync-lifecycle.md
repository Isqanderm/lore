# PR #7: Repository Import Uses Sync Lifecycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `RepositoryImportService` so that `POST /api/v1/repositories/import` delegates the initial sync to `RepositorySyncService.sync_repository(trigger="import")`, ensuring documents get `first_seen_sync_run_id` / `last_seen_sync_run_id` and Repository Brief works immediately after a successful import.

**Architecture:** `RepositoryImportService` becomes a thin orchestration layer: discovery only (`inspect_resource` + `get_or_create ExternalRepository`) then full delegation to `RepositorySyncService`. `RepositorySyncService` remains the single owner of the full sync lifecycle (creates sync run, calls `full_sync`, ingests, marks status, marks inactive). The import route mirrors sync route error handling — commits on generic `Exception` to persist failed sync runs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest, testcontainers (`pgvector/pgvector:pg16`)

---

## File Map

| File | Action | Responsibility after PR |
|---|---|---|
| `lore/ingestion/repository_import.py` | Modify | Thin orchestration: discovery + delegate to sync_service |
| `apps/api/routes/v1/repositories.py` | Modify | Update `_build_import_service`, `ImportResponse` (+`sync_run_id`), error handling |
| `tests/unit/ingestion/test_repository_import_service.py` | **Create** | Unit tests for `RepositoryImportService` orchestration (no DB) |
| `tests/integration/connectors/test_import_api.py` | Modify | Update existing + add 6 new HTTP integration tests |
| `tests/integration/connectors/test_repository_import_flow.py` | **Delete** | Coverage moved to unit + HTTP integration layers |

---

### Task 1: Unit tests — new RepositoryImportService interface (failing)

Write tests that describe the new interface BEFORE implementing it. They will fail until Task 2.

**Files:**
- Create: `tests/unit/ingestion/test_repository_import_service.py`

- [ ] **Step 1.1: Create test file**

Create `tests/unit/ingestion/test_repository_import_service.py` with the following content:

```python
"""Unit tests for RepositoryImportService orchestration.

No DB, no HTTP, no real connector calls past inspect_resource.
Verifies:
- import delegates to sync_service.sync_repository(trigger="import", mode="full")
- ImportResult fields are built from RepositorySyncResult (including versions_skipped)
- connector.full_sync() is never called directly
- ConnectorNotFoundError propagates to caller
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.errors import ConnectorNotFoundError
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
)
from lore.connector_sdk.registry import ConnectorRegistry
from lore.ingestion.repository_import import RepositoryImportService
from lore.sync.models import RepositorySyncResult

pytestmark = pytest.mark.unit

_CONN_ID: UUID = uuid4()
_REPO_ID: UUID = uuid4()
_SYNC_RUN_ID: UUID = uuid4()


# ── Fakes ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeConnection:
    id: UUID


@dataclass
class _FakeRepo:
    id: UUID


class _FakeExtConnectionRepo:
    async def get_or_create_env_pat(self, *, provider: str) -> _FakeConnection:
        return _FakeConnection(id=_CONN_ID)


class _FakeExtRepositoryRepo:
    async def get_or_create(self, *, connection_id: UUID, draft: Any) -> _FakeRepo:
        return _FakeRepo(id=_REPO_ID)


class FakeRepositorySyncService:
    """Returns a real RepositorySyncResult so field mismatches are caught at import time."""

    def __init__(self, result: RepositorySyncResult) -> None:
        self.result = result
        self.calls: list[tuple[UUID, str, str]] = []

    async def sync_repository(
        self,
        repository_id: UUID,
        trigger: str = "manual",
        mode: str = "full",
    ) -> RepositorySyncResult:
        self.calls.append((repository_id, trigger, mode))
        return self.result


class _OkConnector(BaseConnector):
    """Connector whose full_sync() raises AssertionError — guards against direct calls."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="github",
            display_name="OK",
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
            provider="github",
            owner="acme",
            name="myrepo",
            full_name="acme/myrepo",
            default_branch="main",
            html_url="https://github.com/acme/myrepo",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raise AssertionError(
            "RepositoryImportService must not call connector.full_sync() directly"
        )

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return []


def _make_sync_result(**overrides: Any) -> RepositorySyncResult:
    defaults: dict[str, Any] = dict(
        sync_run_id=_SYNC_RUN_ID,
        repository_id=_REPO_ID,
        status="succeeded",
        trigger="import",
        mode="full",
        raw_objects_processed=1,
        documents_created=1,
        versions_created=1,
        versions_skipped=0,
        warnings=[],
    )
    return RepositorySyncResult(**{**defaults, **overrides})


def _make_svc(fake_sync: FakeRepositorySyncService) -> RepositoryImportService:
    registry = ConnectorRegistry()
    registry.register(_OkConnector())
    return RepositoryImportService(
        registry=registry,
        ext_connection_repo=_FakeExtConnectionRepo(),
        ext_repository_repo=_FakeExtRepositoryRepo(),
        sync_service=fake_sync,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_import_delegates_to_sync_service_with_import_trigger() -> None:
    fake_sync = FakeRepositorySyncService(_make_sync_result())
    svc = _make_svc(fake_sync)

    await svc.import_repository("https://github.com/acme/myrepo", "github")

    assert len(fake_sync.calls) == 1
    repo_id, trigger, mode = fake_sync.calls[0]
    assert repo_id == _REPO_ID
    assert trigger == "import"
    assert mode == "full"


async def test_import_returns_sync_result_fields() -> None:
    sync_result = _make_sync_result(
        status="succeeded",
        raw_objects_processed=5,
        documents_created=3,
        versions_created=2,
        versions_skipped=1,
        warnings=["a note"],
    )
    svc = _make_svc(FakeRepositorySyncService(sync_result))

    result = await svc.import_repository("https://github.com/acme/myrepo", "github")

    assert result.status == "succeeded"
    assert result.sync_run_id == _SYNC_RUN_ID
    assert result.repository_id == _REPO_ID
    assert result.connector_id == "github"
    assert result.report.raw_objects_processed == 5
    assert result.report.documents_created == 3
    assert result.report.versions_created == 2
    assert result.report.versions_skipped == 1  # must be passed through
    assert result.report.warnings == ["a note"]


async def test_import_does_not_call_full_sync_directly() -> None:
    # _OkConnector.full_sync() raises AssertionError.
    # FakeRepositorySyncService never calls full_sync.
    # If this completes without error, import_repository never touched connector.full_sync().
    fake_sync = FakeRepositorySyncService(_make_sync_result())
    svc = _make_svc(fake_sync)

    await svc.import_repository("https://github.com/acme/myrepo", "github")


async def test_import_connector_not_found_propagates() -> None:
    registry = ConnectorRegistry()  # empty — no connectors registered
    fake_sync = FakeRepositorySyncService(_make_sync_result())
    svc = RepositoryImportService(
        registry=registry,
        ext_connection_repo=_FakeExtConnectionRepo(),
        ext_repository_repo=_FakeExtRepositoryRepo(),
        sync_service=fake_sync,
    )

    with pytest.raises(ConnectorNotFoundError):
        await svc.import_repository("https://github.com/acme/myrepo", "nonexistent")
```

- [ ] **Step 1.2: Run tests — expect failures**

```bash
pytest tests/unit/ingestion/test_repository_import_service.py -v
```

Expected: all 4 tests FAIL. Likely `TypeError` on `RepositoryImportService.__init__` (current code has `ingestion`, not `sync_service`).

- [ ] **Step 1.3: Commit failing tests**

```bash
git add tests/unit/ingestion/test_repository_import_service.py
git commit -m "test(unit): add failing unit tests for new RepositoryImportService interface"
```

---

### Task 2: Refactor RepositoryImportService

**Files:**
- Modify: `lore/ingestion/repository_import.py`

- [ ] **Step 2.1: Replace file contents entirely**

Replace `lore/ingestion/repository_import.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lore.ingestion.models import IngestionReport

if TYPE_CHECKING:
    from uuid import UUID

    from lore.connector_sdk.registry import ConnectorRegistry
    from lore.infrastructure.db.repositories.external_connection import (
        ExternalConnectionRepository,
    )
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.sync.service import RepositorySyncService


@dataclass
class ImportResult:
    repository_id: UUID
    connector_id: str
    status: str
    report: IngestionReport
    sync_run_id: UUID


class RepositoryImportService:
    """Orchestrates repository discovery, then delegates initial sync to RepositorySyncService."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        ext_connection_repo: ExternalConnectionRepository,
        ext_repository_repo: ExternalRepositoryRepository,
        sync_service: RepositorySyncService,
    ) -> None:
        self._registry = registry
        self._ext_connection_repo = ext_connection_repo
        self._ext_repository_repo = ext_repository_repo
        self._sync_service = sync_service

    async def import_repository(
        self,
        resource_uri: str,
        connector_id: str,
    ) -> ImportResult:
        connector = self._registry.get(connector_id)  # raises ConnectorNotFoundError if missing

        connection = await self._ext_connection_repo.get_or_create_env_pat(provider=connector_id)

        container_draft = await connector.inspect_resource(resource_uri)

        ext_repo = await self._ext_repository_repo.get_or_create(
            connection_id=connection.id,
            draft=container_draft,
        )

        sync_result = await self._sync_service.sync_repository(
            repository_id=ext_repo.id,
            trigger="import",
            mode="full",
        )

        return ImportResult(
            repository_id=ext_repo.id,
            connector_id=connector_id,
            status=sync_result.status,
            sync_run_id=sync_result.sync_run_id,
            report=IngestionReport(
                raw_objects_processed=sync_result.raw_objects_processed,
                documents_created=sync_result.documents_created,
                versions_created=sync_result.versions_created,
                versions_skipped=sync_result.versions_skipped,
                warnings=sync_result.warnings,
            ),
        )
```

- [ ] **Step 2.2: Run unit tests — expect all 4 pass**

```bash
pytest tests/unit/ingestion/test_repository_import_service.py -v
```

Expected:
```
PASSED tests/unit/ingestion/test_repository_import_service.py::test_import_delegates_to_sync_service_with_import_trigger
PASSED tests/unit/ingestion/test_repository_import_service.py::test_import_returns_sync_result_fields
PASSED tests/unit/ingestion/test_repository_import_service.py::test_import_does_not_call_full_sync_directly
PASSED tests/unit/ingestion/test_repository_import_service.py::test_import_connector_not_found_propagates
```

- [ ] **Step 2.3: Run full unit suite — verify no regressions**

```bash
make test-unit
```

Expected: all pass.

- [ ] **Step 2.4: Commit**

```bash
git add lore/ingestion/repository_import.py
git commit -m "feat: refactor RepositoryImportService — discovery + delegate to RepositorySyncService"
```

---

### Task 3: Update route wiring

**Files:**
- Modify: `apps/api/routes/v1/repositories.py`

Three targeted changes: `ImportResponse`, `_build_import_service`, route handler.

- [ ] **Step 3.1: Update `ImportResponse` — add `sync_run_id`**

Find and replace the existing `ImportResponse` class:

```python
# BEFORE
class ImportResponse(BaseModel):
    repository_id: UUID
    connector_id: str
    status: str
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    warnings: list[str] = Field(default_factory=list)
```

Replace with:

```python
class ImportResponse(BaseModel):
    repository_id: UUID
    connector_id: str
    status: str
    sync_run_id: UUID
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 3.2: Replace `_build_import_service` — reuse `_build_sync_service`**

Find and replace the entire `_build_import_service` function:

```python
# BEFORE
def _build_import_service(
    session: AsyncSession, registry: ConnectorRegistry
) -> RepositoryImportService:
    ext_conn_repo = ExternalConnectionRepository(session)
    ext_repo_repo = ExternalRepositoryRepository(session)
    ext_obj_repo = ExternalObjectRepository(session)
    source_repo = SourceRepository(session)
    doc_repo = DocumentRepository(session)
    dv_repo = DocumentVersionRepository(session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    return RepositoryImportService(registry, ingestion, ext_conn_repo, ext_repo_repo)
```

Replace with:

```python
def _build_import_service(
    session: AsyncSession, registry: ConnectorRegistry
) -> RepositoryImportService:
    ext_conn_repo = ExternalConnectionRepository(session)
    ext_repo_repo = ExternalRepositoryRepository(session)
    sync_service = _build_sync_service(session, registry)
    return RepositoryImportService(
        registry=registry,
        ext_connection_repo=ext_conn_repo,
        ext_repository_repo=ext_repo_repo,
        sync_service=sync_service,
    )
```

Note: `IngestionService` stays in the file-level imports — it is still used inside `_build_sync_service()`.

- [ ] **Step 3.3: Update the `import_repository` route handler**

Find and replace the entire `import_repository` route function:

```python
# BEFORE
@router.post("/import", response_model=ImportResponse)
async def import_repository(
    body: ImportRequest,
    request: Request,
    session: SessionDep,
) -> ImportResponse:
    registry = request.app.state.connector_registry
    svc = _build_import_service(session, registry)

    try:
        result = await svc.import_repository(body.url, body.connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExternalResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()

    return ImportResponse(
        repository_id=result.repository_id,
        connector_id=result.connector_id,
        status=result.status,
        raw_objects_processed=result.report.raw_objects_processed,
        documents_created=result.report.documents_created,
        versions_created=result.report.versions_created,
        warnings=result.report.warnings,
    )
```

Replace with:

```python
@router.post("/import", response_model=ImportResponse)
async def import_repository(
    body: ImportRequest,
    request: Request,
    session: SessionDep,
) -> ImportResponse:
    registry = request.app.state.connector_registry
    svc = _build_import_service(session, registry)

    try:
        result = await svc.import_repository(body.url, body.connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExternalResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # If sync run was created before failure, mark_failed() was flushed —
        # commit persists the failed run. May also commit connection/repo if
        # created before sync started; this is acceptable diagnostic state.
        await session.commit()
        raise HTTPException(status_code=500, detail="Import sync failed") from exc

    await session.commit()

    return ImportResponse(
        repository_id=result.repository_id,
        connector_id=result.connector_id,
        status=result.status,
        sync_run_id=result.sync_run_id,
        raw_objects_processed=result.report.raw_objects_processed,
        documents_created=result.report.documents_created,
        versions_created=result.report.versions_created,
        warnings=result.report.warnings,
    )
```

- [ ] **Step 3.4: Run type check**

```bash
make type-check
```

Expected: no new errors.

- [ ] **Step 3.5: Run unit tests**

```bash
make test-unit
```

Expected: all pass.

- [ ] **Step 3.6: Commit**

```bash
git add apps/api/routes/v1/repositories.py
git commit -m "feat: update import route — reuse sync service builder, add sync_run_id to response, fix error handling"
```

---

### Task 4: Update existing HTTP integration tests

**Files:**
- Modify: `tests/integration/connectors/test_import_api.py`

- [ ] **Step 4.1: Fix `test_import_endpoint_returns_200` status assertion**

Find this block in `test_import_endpoint_returns_200`:

```python
    assert data["status"] == "synced"
    assert data["connector_id"] == "fake"
    assert data["documents_created"] == 1
    assert data["versions_created"] == 1
```

Replace with:

```python
    assert data["status"] == "succeeded"
    assert data["connector_id"] == "fake"
    assert "sync_run_id" in data
    assert UUID(data["sync_run_id"])
    assert data["documents_created"] == 1
    assert data["versions_created"] == 1
```

- [ ] **Step 4.2: Run existing tests to verify they still pass**

```bash
pytest tests/integration/connectors/test_import_api.py -v
```

Expected: both `test_import_endpoint_returns_200` and `test_import_endpoint_unknown_connector_returns_404` pass.

- [ ] **Step 4.3: Commit**

```bash
git add tests/integration/connectors/test_import_api.py
git commit -m "test(integration): update import status assertion to 'succeeded', assert sync_run_id present"
```

---

### Task 5: Add new HTTP integration tests

**Files:**
- Modify: `tests/integration/connectors/test_import_api.py`

All 6 new tests go into `test_import_api.py`. Add them after the existing tests.

- [ ] **Step 5.1: Extend imports at the top of `test_import_api.py`**

Add these imports to the existing import block (after the last existing import):

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.models.source import SourceORM
```

- [ ] **Step 5.2: Add partial and failing fake connectors after `_FakeConnector`**

Add these two classes immediately after the `_FakeConnector` class definition:

```python
class _PartialFakeConnector(_FakeConnector):
    """Returns one file plus a warning — triggers status='partial'."""

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        base = await super().full_sync(request)
        return SyncResult(
            connector_id=base.connector_id,
            raw_objects=base.raw_objects,
            warnings=["rate limit hit — some files skipped"],
        )


class _FailingFakeConnector(_FakeConnector):
    """inspect_resource succeeds; full_sync raises — triggers failed sync run."""

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raise RuntimeError("network failure")
```

- [ ] **Step 5.3: Add fixtures for partial and failing connectors after `fake_registry`**

```python
@pytest.fixture
def partial_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(_PartialFakeConnector())
    return registry


@pytest.fixture
def failing_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(_FailingFakeConnector())
    return registry
```

- [ ] **Step 5.4: Add DB helper**

Add this helper function after the fixtures:

```python
async def _get_repo_by_full_name(
    session: AsyncSession, full_name: str
) -> ExternalRepositoryORM | None:
    result = await session.execute(
        select(ExternalRepositoryORM).where(ExternalRepositoryORM.full_name == full_name)
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 5.5: Add test A — import creates sync run with trigger="import"**

```python
@pytest.mark.integration
async def test_import_creates_sync_run_with_import_trigger(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    fake_registry: ConnectorRegistry,
    db_session: AsyncSession,
) -> None:
    app_with_db.state.connector_registry = fake_registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "fake"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    sync_run_id = UUID(data["sync_run_id"])
    repository_id = UUID(data["repository_id"])

    result = await db_session.execute(
        select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == sync_run_id)
    )
    run = result.scalar_one_or_none()

    assert run is not None
    assert run.repository_id == repository_id
    assert run.trigger == "import"
    assert run.mode == "full"
    assert run.status == "succeeded"
```

- [ ] **Step 5.6: Add test B — imported documents have sync tracking**

```python
@pytest.mark.integration
async def test_imported_documents_have_sync_tracking(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    fake_registry: ConnectorRegistry,
    db_session: AsyncSession,
) -> None:
    app_with_db.state.connector_registry = fake_registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "fake"},
    )
    assert response.status_code == 200
    data = response.json()
    sync_run_id = UUID(data["sync_run_id"])
    repository_id = UUID(data["repository_id"])

    db_session.expire_all()

    stmt = (
        select(DocumentORM)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == repository_id)
    )
    result = await db_session.execute(stmt)
    docs = result.scalars().all()

    assert len(docs) == 1
    doc = docs[0]
    assert doc.is_active is True
    assert doc.deleted_at is None
    assert doc.first_seen_sync_run_id == sync_run_id
    assert doc.last_seen_sync_run_id == sync_run_id
```

- [ ] **Step 5.7: Add test C — brief works after successful import**

```python
@pytest.mark.integration
async def test_brief_can_be_generated_after_successful_import(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    fake_registry: ConnectorRegistry,
) -> None:
    app_with_db.state.connector_registry = fake_registry

    import_resp = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "fake"},
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["status"] == "succeeded"
    repository_id = import_resp.json()["repository_id"]

    brief_resp = await app_client_with_db.post(
        f"/api/v1/repositories/{repository_id}/brief/generate"
    )
    assert brief_resp.status_code == 200
    brief_data = brief_resp.json()
    # Brief was built from the import sync run — must contain file stats
    assert brief_data["brief"]["stats"]["total_files"] > 0
```

- [ ] **Step 5.8: Add test D — partial import creates partial sync run**

```python
@pytest.mark.integration
async def test_partial_import_creates_partial_sync_run(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    partial_registry: ConnectorRegistry,
    db_session: AsyncSession,
) -> None:
    app_with_db.state.connector_registry = partial_registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "fake"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    sync_run_id = UUID(data["sync_run_id"])
    repository_id = UUID(data["repository_id"])

    result = await db_session.execute(
        select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == sync_run_id)
    )
    run = result.scalar_one_or_none()
    assert run is not None
    assert run.status == "partial"
    assert run.trigger == "import"

    doc_result = await db_session.execute(
        select(DocumentORM)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == repository_id)
    )
    docs = doc_result.scalars().all()
    assert len(docs) == 1
    assert docs[0].is_active is True
    assert docs[0].last_seen_sync_run_id == sync_run_id
```

- [ ] **Step 5.9: Add test E — failed import persists failed sync run**

```python
@pytest.mark.integration
async def test_failed_import_persists_failed_sync_run(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    failing_registry: ConnectorRegistry,
    db_session: AsyncSession,
) -> None:
    app_with_db.state.connector_registry = failing_registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "fake"},
    )
    assert response.status_code == 500

    db_session.expire_all()

    # repository_id is not in the 500 response — find repo via full_name
    repo = await _get_repo_by_full_name(db_session, "acme/apirepo")
    assert repo is not None, "ExternalRepository should have been committed before sync started"

    result = await db_session.execute(
        select(RepositorySyncRunORM)
        .where(RepositorySyncRunORM.repository_id == repo.id)
        .where(RepositorySyncRunORM.trigger == "import")
    )
    run = result.scalar_one_or_none()
    assert run is not None
    assert run.status == "failed"
    assert run.error_message is not None
    assert "network failure" in run.error_message
```

- [ ] **Step 5.10: Add test F — provenance in document version**

```python
@pytest.mark.integration
async def test_import_provenance_in_document_version(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    fake_registry: ConnectorRegistry,
    db_session: AsyncSession,
) -> None:
    app_with_db.state.connector_registry = fake_registry

    response = await app_client_with_db.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/apirepo", "connector_id": "fake"},
    )
    assert response.status_code == 200
    repository_id = UUID(response.json()["repository_id"])

    db_session.expire_all()

    stmt = (
        select(DocumentVersionORM)
        .join(DocumentORM, DocumentVersionORM.document_id == DocumentORM.id)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == repository_id)
    )
    result = await db_session.execute(stmt)
    versions = result.scalars().all()

    assert len(versions) == 1
    meta = versions[0].metadata_
    assert "commit_sha" in meta
    assert "external_id" in meta
    assert "raw_payload_hash" in meta
```

- [ ] **Step 5.11: Run all integration tests for import API**

```bash
pytest tests/integration/connectors/test_import_api.py -v
```

Expected: all 8 tests pass (2 existing + 6 new).

- [ ] **Step 5.12: Commit**

```bash
git add tests/integration/connectors/test_import_api.py
git commit -m "test(integration): add sync run, document tracking, brief, partial, failed, and provenance tests for import"
```

---

### Task 6: Delete test_repository_import_flow.py

Coverage is now in:
- `tests/unit/ingestion/test_repository_import_service.py` — orchestration
- `tests/integration/connectors/test_import_api.py` — provenance + DB state

**Files:**
- Delete: `tests/integration/connectors/test_repository_import_flow.py`

- [ ] **Step 6.1: Remove the file**

```bash
git rm tests/integration/connectors/test_repository_import_flow.py
```

- [ ] **Step 6.2: Verify nothing imports from it**

```bash
grep -r "test_repository_import_flow" /Users/$(whoami)/lore/lore --include="*.py" --include="*.ini" --include="*.toml" --include="*.cfg"
```

Expected: no output.

- [ ] **Step 6.3: Commit**

```bash
git commit -m "test: remove test_repository_import_flow.py — coverage moved to unit and HTTP integration layers"
```

---

### Task 7: Full test suite

- [ ] **Step 7.1: Unit tests**

```bash
make test-unit
```

Expected: all pass, including new `test_repository_import_service.py`.

- [ ] **Step 7.2: Integration tests**

```bash
make test-integration
```

Expected: all pass. Key files to verify:
- `tests/integration/connectors/test_import_api.py` — 8 tests
- `tests/integration/connectors/test_sync_api.py` — unchanged
- `tests/integration/connectors/test_sync_document_lifecycle.py` — unchanged
- `tests/integration/test_repository_brief_active_documents.py` — unchanged

- [ ] **Step 7.3: Lint + type check**

```bash
make lint && make type-check
```

Expected: no issues.

- [ ] **Step 7.4: Commit final**

```bash
git commit --allow-empty -m "chore: PR #7 complete — import uses sync lifecycle"
```

---

## Acceptance Checklist

Before calling this done, verify each item against the spec:

- [ ] `RepositoryImportService` no longer imports `FullSyncRequest`
- [ ] `RepositoryImportService` no longer depends on `IngestionService`
- [ ] `RepositoryImportService` no longer calls `connector.full_sync()` directly
- [ ] `RepositoryImportService` no longer calls `ext_repository_repo.mark_synced()`
- [ ] Successful import → `RepositorySyncRun` with `trigger="import"`, `status="succeeded"`
- [ ] Partial import → `RepositorySyncRun` with `status="partial"`
- [ ] Failed `full_sync` → `RepositorySyncRun` with `status="failed"`, committed to DB
- [ ] Imported documents have `first_seen_sync_run_id` and `last_seen_sync_run_id` set
- [ ] Repository Brief generates successfully after successful import
- [ ] `ImportResponse` includes `sync_run_id`
- [ ] Import returns `"succeeded"` or `"partial"` — never legacy `"synced"`
- [ ] All existing sync and ingestion tests pass unchanged
- [ ] No LLM / embeddings / agents / webhooks / scheduler code added
