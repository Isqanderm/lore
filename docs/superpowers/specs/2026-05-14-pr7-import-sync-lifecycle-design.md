# PR #7 Design: Repository Import Uses Sync Lifecycle

**Date:** 2026-05-14
**Status:** Approved

---

## Problem

`RepositoryImportService` has its own duplicated sync lifecycle:

```
inspect_resource → get/create repo → connector.full_sync() → IngestionService.ingest_sync_result() → mark_synced()
```

This means documents imported via `POST /api/v1/repositories/import` end up with:
- `first_seen_sync_run_id = NULL`
- `last_seen_sync_run_id = NULL`
- No `RepositorySyncRun` record exists
- Status returns legacy `"synced"` instead of `"succeeded"`/`"partial"`

This is inconsistent with the sync lifecycle introduced in PR #6. Repository Brief (PR #5) depends on a latest succeeded `RepositorySyncRun` — without one, Brief generation fails immediately after import.

---

## Goal

Make import = repository discovery + initial sync via `RepositorySyncService`.

After this PR:
1. `POST /repositories/import` still creates or finds `ExternalRepository`.
2. Import delegates the actual data fetch to `RepositorySyncService.sync_repository(trigger="import", mode="full")`.
3. Import creates a `RepositorySyncRun` with `trigger="import"`.
4. Documents imported during initial sync get `first_seen_sync_run_id` and `last_seen_sync_run_id` set.
5. Repository Brief can be generated immediately after a successful import.
6. Import returns `status="succeeded"` or `"partial"` (never legacy `"synced"`).
7. Failed import persists a `RepositorySyncRun` with `status="failed"`.
8. Manual sync behavior is unchanged.

---

## Architecture: Approach A — Full delegation to RepositorySyncService

`RepositoryImportService` becomes a thin orchestration service:
- **Discovery phase:** `inspect_resource` + `get_or_create` repo (owned by import service)
- **Sync phase:** delegate entirely to `RepositorySyncService.sync_repository(trigger="import")`

`RepositorySyncService` remains the single place that owns the full sync lifecycle (invariant from CLAUDE.md).

Approaches B (import service creates sync run itself) and C (collapse into route handler) were rejected: B duplicates lifecycle, C violates thin-route convention.

---

## Core changes

### 1. `lore/ingestion/repository_import.py`

**ImportResult** — add `sync_run_id`:

```python
@dataclass
class ImportResult:
    repository_id: UUID
    connector_id: str
    status: str
    report: IngestionReport
    sync_run_id: UUID
```

**RepositoryImportService docstring** — update to reflect new responsibility:

```python
"""Orchestrates repository discovery, then delegates initial sync to RepositorySyncService."""
```

**RepositoryImportService constructor** — remove `ingestion`, add `sync_service`:

```python
class RepositoryImportService:
    def __init__(
        self,
        registry: ConnectorRegistry,
        ext_connection_repo: ExternalConnectionRepository,
        ext_repository_repo: ExternalRepositoryRepository,
        sync_service: RepositorySyncService,  # TYPE_CHECKING import
    ) -> None:
```

**`import_repository()` flow:**

```python
async def import_repository(self, resource_uri: str, connector_id: str) -> ImportResult:
    connector = self._registry.get(connector_id)           # raises ConnectorNotFoundError

    connection = await self._ext_connection_repo.get_or_create_env_pat(
        provider=connector_id,
    )

    container_draft = await connector.inspect_resource(resource_uri)  # raises ExternalResourceNotFoundError

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

**Removed from imports:** `FullSyncRequest`, `datetime`, `UTC`, `IngestionService` (TYPE_CHECKING).

**Added to imports:** `RepositorySyncService` (TYPE_CHECKING), `IngestionReport` (runtime, for report construction).

### 2. `apps/api/routes/v1/repositories.py`

**`ImportResponse`** — add `sync_run_id`:

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

**`_build_import_service()`** — reuse `_build_sync_service()`, add `ext_repository_repo`:

```python
def _build_import_service(
    session: AsyncSession,
    registry: ConnectorRegistry,
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

Note: `IngestionService`, `ExternalObjectRepository`, `SourceRepository`, `DocumentRepository`, `DocumentVersionRepository` are no longer constructed in `_build_import_service()` — they're already built inside `_build_sync_service()`.

**`import_repository` route** — add `except Exception` block, mirror sync route.

Note: `except Exception` commits the session before re-raising. If the failure occurred after `get_or_create` (connection/repo) but before the sync run was created, those records will be committed. This is acceptable: a failed import may leave an `ExternalRepository` as diagnostic state, consistent with manual sync behavior.



```python
@router.post("/import", response_model=ImportResponse)
async def import_repository(body: ImportRequest, request: Request, session: SessionDep) -> ImportResponse:
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
        # If failure happened after sync run was created, mark_failed() was flushed —
        # commit here persists the failed run (mirrors sync route behavior).
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

**File-level imports:** `IngestionService` stays — it is still used inside `_build_sync_service()`. No import removal needed in the route file.

---

## Fake connector constraints (tests)

The existing `_FakeConnector` in `test_import_api.py` uses `connector_id="fake"` / `provider="fake"` — this is acceptable. `RepositorySyncService` will look up `repo.provider="fake"` from DB and call `registry.get("fake")`, which works because the same registry is passed through the request app state.

**Critical:** fake connector must keep `object_type="github.file"`. Current active-state logic (`mark_missing_github_files_inactive`) filters by this object type. If changed, Brief and active-document tests will silently break.

For the **failed import** test (test E), the fake must fail in `full_sync()`, not `inspect_resource()`. If `inspect_resource` fails, no sync run has been created yet and the "failed run persists" assertion cannot hold. Use a mutable fake with `raise_on_full_sync` flag:

```python
class _FailingFakeConnector(_FakeConnector):
    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raise RuntimeError("network failure")
```

---

## Test strategy

### A. Unit tests — `tests/unit/ingestion/test_repository_import_service.py` (new)

Tests for `RepositoryImportService` as thin orchestration. No DB, no HTTP. Uses fake repositories and `FakeRepositorySyncService`.

```python
from lore.sync.models import RepositorySyncResult  # must use real dataclass

class FakeRepositorySyncService:
    def __init__(self, result: RepositorySyncResult) -> None:
        self.result = result
        self.calls: list[tuple[UUID, str, str]] = []

    async def sync_repository(self, repository_id, trigger="manual", mode="full"):
        self.calls.append((repository_id, trigger, mode))
        return self.result
```

`FakeRepositorySyncService` must return a real `RepositorySyncResult` (not an ad-hoc object). This ensures that field mismatches between `RepositorySyncResult` and `ImportResult` mapping are caught by the test.

Required tests:

| Test | Asserts |
|---|---|
| `test_import_delegates_to_sync_service_with_import_trigger` | `sync_service.calls == [(repo.id, "import", "full")]` |
| `test_import_returns_sync_result_fields` | `ImportResult.status`, `sync_run_id`, `report.*` (including `versions_skipped`) match `RepositorySyncResult` |
| `test_import_does_not_call_full_sync_directly` | fake connector's `full_sync` raises `AssertionError`; test passes because service never calls it |
| `test_import_connector_not_found_propagates` | `ConnectorNotFoundError` is not caught by service |

### B. HTTP integration tests — `tests/integration/connectors/test_import_api.py` (update + new)

**Update existing:**
- `test_import_endpoint_returns_200`: `status == "synced"` → `"succeeded"`; assert `"sync_run_id" in data` and `UUID(data["sync_run_id"])` is valid

**Add new:**

| Test | Asserts |
|---|---|
| `test_import_creates_sync_run_with_import_trigger` | DB has `RepositorySyncRunORM` with `trigger="import"`, `mode="full"`, `status="succeeded"` |
| `test_imported_documents_have_sync_tracking` | `document.first_seen_sync_run_id == import_sync_run_id` and `last_seen_sync_run_id == import_sync_run_id` |
| `test_brief_can_be_generated_after_successful_import` | POST import (succeeded) → POST brief → 200, `stats.total_files > 0` |
| `test_partial_import_creates_partial_sync_run` | fake returns warnings → response `status="partial"`, DB run `status="partial"` |
| `test_failed_import_persists_failed_sync_run` | fake fails in `full_sync` → 500; find repo by `full_name` in DB (not from 500 response), assert `RepositorySyncRunORM.trigger="import"`, `status="failed"` |
| `test_import_provenance_in_document_version` | `DocumentVersionORM.metadata_` contains `commit_sha`, `external_id`, `raw_payload_hash` |

### C. Delete old integration file

`tests/integration/connectors/test_repository_import_flow.py` — delete after provenance coverage moves to `test_import_api.py`. It directly wires `IngestionService` into `RepositoryImportService`, which is architecturally incorrect after PR #7.

---

## What does NOT change

- `RepositorySyncService.sync_repository()` — unchanged
- `IngestionService.ingest_sync_result()` — unchanged (still accepts `sync_run_id=None` for legacy use)
- Manual sync route (`POST /{id}/sync`) — unchanged
- `mark_missing_github_files_inactive` logic — unchanged
- All existing sync lifecycle tests (`test_sync_api.py`, `test_sync_document_lifecycle.py`) — must still pass

---

## Non-goals (explicitly out of scope)

- Automatic brief generation after import
- Commit SHA tracking
- Incremental sync
- Branch-specific sync
- Webhook / scheduled sync
- Background job processing
- LLM, embeddings, semantic analysis

---

## Acceptance criteria

PR #7 is complete when:

1. `RepositoryImportService` no longer imports or uses `FullSyncRequest`
2. `RepositoryImportService` no longer depends on `IngestionService`
3. `RepositoryImportService` no longer calls `connector.full_sync()` directly
4. `RepositoryImportService` no longer calls `ext_repository_repo.mark_synced()`
5. Successful import creates `RepositorySyncRun` with `trigger="import"`, `status="succeeded"`
6. Partial import creates `RepositorySyncRun` with `status="partial"`
7. Failed import (during `full_sync`) persists `RepositorySyncRun` with `status="failed"`
8. Imported documents have `first_seen_sync_run_id` and `last_seen_sync_run_id` set
9. Repository Brief can be generated immediately after successful import
10. `ImportResponse` includes `sync_run_id`
11. Import returns `status="succeeded"` or `"partial"` (not `"synced"`)
12. All existing sync and ingestion tests pass
13. No LLM/embeddings/agents/webhooks/scheduler added
