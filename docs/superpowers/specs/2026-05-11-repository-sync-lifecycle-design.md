# Repository Sync Lifecycle — Design Spec

**Date:** 2026-05-11  
**PR:** #3  
**Status:** Approved

---

## 1. Goal

Add a provider-agnostic repository sync lifecycle for already-imported repositories.

- `import` = first-time registration (handled by `RepositoryImportService`, unchanged)
- `sync` = repeatable refresh of an existing repository — this PR

The first provider is GitHub; the sync layer must be generic enough to later support GitLab or others.

---

## 2. Scope

**In scope:**
- `repository_sync_runs` table + ORM + repository
- `RepositorySyncService` (provider-agnostic)
- `POST /api/v1/repositories/{repository_id}/sync`
- `GET /api/v1/repositories/{repository_id}/sync-runs`
- Integration tests (A–G) using a fake connector

**Explicitly out of scope:**
- GitHub webhooks
- Scheduled or incremental sync
- Queue / background workers
- GitHub App auth
- PR / issues ingestion
- Generated artifacts, repository brief, staleness detection
- Import integration with sync_runs (left as TODO)

---

## 3. Architecture

### Component responsibilities

| Component | Role |
|---|---|
| `RepositoryImportService` | First-time import — unchanged. TODO: record sync_run with trigger="import" in a future PR. |
| `RepositorySyncService` | Provider-agnostic sync lifecycle orchestration |
| `GitHubConnector` | Fetches and normalizes external data — unchanged |
| `IngestionService` | Persists canonical documents/versions — unchanged |
| `RepositorySyncRunRepository` | Records sync lifecycle, counters, warnings, failures |

### Data flow

```
POST /repositories/{id}/sync
  → RepositorySyncService.sync_repository(repository_id, trigger="manual", mode="full")
      → ExternalRepositoryRepository.get_by_id()           # raises RepositoryNotFoundError if None
      → ConnectorRegistry.get(repo.provider)                # raises ConnectorNotFoundError if missing
      → RepositorySyncRunRepository.create_running(...)     # before try — always recorded
      → try:
            connector.full_sync(FullSyncRequest)
            IngestionService.ingest_sync_result(sync_result, connector)
            RepositorySyncRunRepository.mark_finished(status=succeeded|partial, counters)
            ExternalRepositoryRepository.mark_synced(repo.id, now())
            return RepositorySyncResult(...)
         except Exception:
            RepositorySyncRunRepository.mark_failed(run.id, error_message=str(exc))
            raise
```

**Critical invariant:** `create_running()` is called **before** the `try` block. `mark_failed()` fires on any exception, including connector and ingestion failures.

### Status determination

| Condition | status |
|---|---|
| `report.warnings` is empty | `"succeeded"` |
| `report.warnings` is non-empty | `"partial"` |
| Exception raised | `"failed"` |

`IngestionReport.warnings` is seeded from `sync_result.warnings` (per-file fetch errors from the connector), so a single `bool(report.warnings)` check covers both connector and ingestion warnings.

---

## 4. New files

### `migrations/versions/0003_repository_sync_runs.py`

Creates `repository_sync_runs` table:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `repository_id` | UUID NOT NULL FK → external_repositories | |
| `connector_id` | TEXT NOT NULL | |
| `trigger` | TEXT NOT NULL | import / manual / webhook / scheduled |
| `mode` | TEXT NOT NULL | full / incremental |
| `status` | TEXT NOT NULL | running / succeeded / failed / partial |
| `started_at` | TIMESTAMPTZ nullable | set on create_running |
| `finished_at` | TIMESTAMPTZ nullable | set on mark_finished / mark_failed |
| `raw_objects_processed` | INTEGER NOT NULL DEFAULT 0 | |
| `documents_created` | INTEGER NOT NULL DEFAULT 0 | |
| `versions_created` | INTEGER NOT NULL DEFAULT 0 | |
| `versions_skipped` | INTEGER NOT NULL DEFAULT 0 | |
| `warnings` | JSONB NOT NULL DEFAULT '[]' | |
| `error_message` | TEXT nullable | |
| `metadata` | JSONB NOT NULL DEFAULT '{}' | |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Indexes:
- `ix_repository_sync_runs_repository_id_created_at` on `(repository_id, created_at)`
- `ix_repository_sync_runs_repository_id_status` on `(repository_id, status)`
- `ix_repository_sync_runs_connector_id` on `(connector_id)`

### `lore/infrastructure/db/models/repository_sync_run.py`

`RepositorySyncRunORM(Base)` — follows `ExternalRepositoryORM` style (Mapped columns, JSONB, DateTime(timezone=True), func.now()). `updated_at` must use `onupdate=func.now()` so SQLAlchemy auto-updates it on mark_finished / mark_failed.

### `lore/infrastructure/db/repositories/repository_sync_run.py`

`RepositorySyncRun` dataclass + `RepositorySyncRunRepository(BaseRepository[RepositorySyncRunORM])`.

Four methods:
1. `create_running(repository_id, connector_id, trigger, mode) → RepositorySyncRun`
   - Sets `status="running"`, `started_at=now()`, flushes
2. `mark_finished(run_id, status, raw_objects_processed, documents_created, versions_created, versions_skipped, warnings, metadata)`
   - Sets `finished_at=now()`, updates counters
3. `mark_failed(run_id, error_message)`
   - Sets `status="failed"`, `finished_at=now()`, `error_message`
4. `list_by_repository(repository_id, limit=50) → list[RepositorySyncRun]`
   - ORDER BY `created_at DESC`

### `lore/sync/__init__.py`
Empty package marker.

### `lore/sync/errors.py`

```python
class RepositoryNotFoundError(Exception): ...
class UnsupportedSyncModeError(Exception): ...
```

### `lore/sync/models.py`

```python
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
    warnings: list[str]
```

### `lore/sync/service.py`

```python
class RepositorySyncService:
    def __init__(
        self,
        registry: ConnectorRegistry,
        ingestion: IngestionService,
        ext_repo_repo: ExternalRepositoryRepository,
        sync_run_repo: RepositorySyncRunRepository,
    ) -> None: ...

    async def sync_repository(
        self,
        repository_id: UUID,
        trigger: str = "manual",
        mode: str = "full",
    ) -> RepositorySyncResult: ...
```

---

## 5. Modified files

### `apps/api/routes/v1/repositories.py`

Add to existing router:

**`POST /{repository_id}/sync`**
- Calls `_build_sync_service(session, registry)` → `RepositorySyncService`
- `404` on `RepositoryNotFoundError` or `ConnectorNotFoundError`
- `422` on `UnsupportedSyncModeError`
- `200` with `RepositorySyncResponse`

**`GET /{repository_id}/sync-runs`**
- First checks `ExternalRepositoryRepository.get_by_id()` → `404` if None
- Then calls `RepositorySyncRunRepository.list_by_repository()`
- Returns `list[RepositorySyncRunListItem]` (no pagination wrapper — consistent with existing routes)

**New Pydantic schemas:**

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
    warnings: list[str]

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

**DI builder:**

```python
def _build_sync_service(session, registry) -> RepositorySyncService:
    ext_repo_repo = ExternalRepositoryRepository(session)
    ext_obj_repo = ExternalObjectRepository(session)
    source_repo = SourceRepository(session)
    doc_repo = DocumentRepository(session)
    dv_repo = DocumentVersionRepository(session)
    sync_run_repo = RepositorySyncRunRepository(session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    return RepositorySyncService(registry, ingestion, ext_repo_repo, sync_run_repo)
```

### `lore/infrastructure/db/models/__init__.py`

Add import of `repository_sync_run` module (for `Base.metadata.create_all` to include the table).

### `tests/integration/conftest.py`

Add `repository_sync_run` to the model imports block (same pattern as existing models).

---

## 6. Tests

File: `tests/integration/connectors/test_sync_api.py`

All tests: `@pytest.mark.integration`, fake connector, no real GitHub token.

| ID | Name | Description |
|---|---|---|
| A | `test_sync_endpoint_returns_200` | Sync existing repo → 200, sync_run created, status=succeeded, counters present |
| B | `test_sync_does_not_create_duplicate_repository` | Count repos before/after sync — unchanged |
| C | `test_repeat_sync_same_content_no_new_versions` | Run twice same content → second run versions_created=0 |
| D | `test_sync_changed_content_creates_new_version` | Run with content A, then content B → second run versions_created=1 |
| E | `test_failed_sync_marks_run_as_failed` | Fake connector raises → sync_run.status=failed, error_message set |
| F | `test_list_sync_runs_newest_first` | Create multiple runs → GET returns newest first, fields present |
| G | `test_sync_nonexistent_repository_returns_404` | POST sync for unknown UUID → 404 |

**Fake connector design:**

```python
class _FakeSyncConnector(BaseConnector):
    def __init__(self, content: str = "# Hello", raise_on_sync: Exception | None = None): ...
    async def full_sync(self, request) -> SyncResult:
        if self._raise_on_sync:
            raise self._raise_on_sync
        # return single RawExternalObject with self._content
```

Content-based idempotency test (C/D): instantiate connector with different `content` values.

---

## 7. Error handling

| Error | HTTP status |
|---|---|
| `RepositoryNotFoundError` | 404 |
| `ConnectorNotFoundError` (existing) | 404 (consistent with import route) |
| `UnsupportedSyncModeError` | 422 |
| Connector / ingestion failure | `mark_failed()` + re-raise → 500 |

---

## 8. Import integration (intentional TODO)

`RepositoryImportService.import_repository()` is **unchanged** in this PR.

A comment will be added:
```python
# TODO: record sync_run with trigger="import" once RepositoryImportService
# is refactored to delegate ingestion to RepositorySyncService.
```

---

## 9. Idempotency

Full sync is idempotent through existing `content_hash` / `DocumentVersion` logic in `IngestionService._upsert_document()`. No changes needed.

Expected behavior:
- First sync: creates documents and versions
- Re-sync same content: `versions_skipped` increases, `versions_created=0`
- Re-sync changed content: new `DocumentVersion` created for changed documents only

---

## 10. Definition of done

- [ ] `repository_sync_runs` table exists in migration
- [ ] `RepositorySyncService` is provider-agnostic (no GitHub-specific code)
- [ ] `POST /api/v1/repositories/{repository_id}/sync` works
- [ ] `GET /api/v1/repositories/{repository_id}/sync-runs` works
- [ ] Manual full sync works for existing repositories
- [ ] Sync does not create duplicate `external_repository` rows
- [ ] Repeated sync without changes: `versions_created=0`
- [ ] Changed content: new `document_version` created
- [ ] Failures recorded as `status=failed` with `error_message`
- [ ] Tests A–G pass without real GitHub access
- [ ] No webhook / incremental / artifact code introduced
- [ ] `lore/` and `tests/` pass ruff, mypy strict, pytest
