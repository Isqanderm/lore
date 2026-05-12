# PR #6 Design — Active Repository Document State and Deleted File Handling

**Date:** 2026-05-12  
**Status:** Approved  
**Scope:** Backend correctness only. No LLM, no embeddings, no API contract changes.

---

## Goal

Make Lore's persisted repository documents reflect the current GitHub file state after successful repository syncs.

After this PR:
1. Sync a repository.
2. Detect which GitHub files currently exist.
3. Mark previously known but now-missing GitHub files as inactive/deleted.
4. Generate Repository Brief only from active GitHub file documents.

---

## Hard Constraints

- Do NOT physically delete DocumentORM records.
- Do NOT delete SourceORM, ExternalObjectORM, DocumentVersionORM, or ChunkORM records.
- Do NOT add LLM, embeddings, semantic search, agents, background workers, webhooks.
- Do NOT add scheduled sync, branch support, file history API, restore API, artifact history.
- Do NOT change Repository Brief API/product contract.
- Do NOT expand import flow or refactor RepositoryImportService.
- inactive_count persistence must not cause API/response model changes.

---

## 1. Migration: `0005_document_active_state.py`

Add to `documents` table:

```sql
is_active              BOOLEAN NOT NULL DEFAULT TRUE
deleted_at             TIMESTAMP WITH TIME ZONE NULL
first_seen_sync_run_id UUID NULL REFERENCES repository_sync_runs(id)
last_seen_sync_run_id  UUID NULL REFERENCES repository_sync_runs(id)
```

Indexes:
- `ix_documents_is_active` on `(is_active)`
- `ix_documents_first_seen_sync_run_id` on `(first_seen_sync_run_id)`
- `ix_documents_last_seen_sync_run_id` on `(last_seen_sync_run_id)`

Migration requirements:
- Existing rows get `is_active=true` by DEFAULT — no explicit backfill needed.
- `deleted_at`, `first_seen_sync_run_id`, `last_seen_sync_run_id` remain NULL for pre-existing rows.
- NULL sync IDs mean "pre-state-tracking document" — do not attempt to backfill.

Follow the style of `0004_repository_artifacts.py`: use `op.add_column()` since this adds columns to an existing table (not `op.create_table()`). Use named FK constraints consistent with existing migration style.

---

## 2. DocumentORM — `lore/infrastructure/db/models/document.py`

Add 4 fields using `Mapped` + `mapped_column`, consistent with existing ORM style:

```python
is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true", index=True)
deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
first_seen_sync_run_id: Mapped[UUID | None] = mapped_column(
    ForeignKey("repository_sync_runs.id"), nullable=True, index=True
)
last_seen_sync_run_id: Mapped[UUID | None] = mapped_column(
    ForeignKey("repository_sync_runs.id"), nullable=True, index=True
)
```

---

## 3. Document Schema — `lore/schema/document.py`

Add 4 fields with defaults to the `Document` frozen dataclass:

```python
is_active: bool = True
deleted_at: datetime | None = None
first_seen_sync_run_id: UUID | None = None
last_seen_sync_run_id: UUID | None = None
```

All 4 have defaults — existing code that constructs `Document(...)` without these fields continues to work without changes.

---

## 4. DocumentRepository — `lore/infrastructure/db/repositories/document.py`

### 4a. Update `_doc_orm_to_schema()`

Map the 4 new fields:

```python
is_active=orm.is_active,
deleted_at=orm.deleted_at,
first_seen_sync_run_id=orm.first_seen_sync_run_id,
last_seen_sync_run_id=orm.last_seen_sync_run_id,
```

### 4b. Update `create()`

Write the 4 new fields when constructing `DocumentORM`:

```python
is_active=doc.is_active,
deleted_at=doc.deleted_at,
first_seen_sync_run_id=doc.first_seen_sync_run_id,
last_seen_sync_run_id=doc.last_seen_sync_run_id,
```

### 4c. New method: `mark_seen_in_sync(document_id, sync_run_id) → None`

Atomic single-row UPDATE:

```sql
UPDATE documents SET
  is_active = true,
  deleted_at = NULL,
  first_seen_sync_run_id = COALESCE(first_seen_sync_run_id, :sync_run_id),
  last_seen_sync_run_id = :sync_run_id,
  updated_at = now()
WHERE id = :document_id
```

SQLAlchemy implementation:

```python
from sqlalchemy import func, update

stmt = (
    update(DocumentORM)
    .where(DocumentORM.id == document_id)
    .values(
        is_active=True,
        deleted_at=None,
        first_seen_sync_run_id=func.coalesce(DocumentORM.first_seen_sync_run_id, sync_run_id),
        last_seen_sync_run_id=sync_run_id,
        updated_at=func.now(),
    )
    .execution_options(synchronize_session=False)
)
await self.session.execute(stmt)
```

This method must be called even when the file content is unchanged and no new `DocumentVersion` is created.

### 4d. New method: `mark_missing_github_files_inactive(repository_id, sync_run_id) → int`

Bulk UPDATE using `WHERE id IN (SELECT ...)`. Do NOT use `.scalar_subquery()` — use a plain `select()` inside `.in_()`.

```python
from sqlalchemy import func, or_, select, update

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

Critical correctness rules:
- `DocumentORM.is_active.is_(True)` — already inactive documents are NOT touched. This preserves the original `deleted_at` timestamp from when the file first disappeared.
- `or_(last_seen_sync_run_id.is_(None), last_seen_sync_run_id != sync_run_id)` — handles pre-existing documents with NULL `last_seen_sync_run_id`.
- Returns `result.rowcount or 0` — safe against None.

### 4e. New method: `get_active_document_paths_by_repository_id(repository_id) → list[str]`

Like existing `get_document_paths_by_repository_id()`, with one additional filter:

```python
.where(
    ExternalObjectORM.repository_id == repository_id,
    ExternalObjectORM.object_type == _GITHUB_FILE_OBJECT_TYPE,
    DocumentORM.is_active.is_(True),   # NEW
)
```

Keep all other behavior: distinct, order_by path. Keep the old method in place — existing tests and imports depend on it.

---

## 5. IngestionService — `lore/ingestion/service.py`

### 5a. Updated signature

```python
async def ingest_sync_result(
    self,
    sync_result: SyncResult,
    connector: BaseConnector,
    sync_run_id: UUID | None = None,   # NEW, optional for legacy import flow
) -> IngestionReport:
```

Propagate `sync_run_id` into `_upsert_document()`:

```python
async def _upsert_document(
    self,
    draft: CanonicalDocumentDraft,
    raw: RawExternalObject,
    external_object_id: UUID,
    sync_run_id: UUID | None = None,   # NEW
) -> tuple[bool, bool]:
```

### 5b. Correct call order inside `_upsert_document`

```
1. Upsert raw object (already done before this method)
2. Find or create source
3. Find or create document
4. ← mark_seen_in_sync(doc.id, sync_run_id) if sync_run_id is not None  ← MUST happen here
5. Check latest version checksum — may return early if unchanged
6. Create new version only if content changed
```

Step 4 must happen before the early-return at step 5. A file can be unchanged in content but still present in the sync — it must update `last_seen_sync_run_id`.

### 5c. Legacy import flow

`RepositoryImportService` continues calling `ingest_sync_result()` without `sync_run_id`. This path passes `sync_run_id=None`, `mark_seen_in_sync` is never called, and documents get `is_active=true` with NULL sync IDs. All existing import tests continue to pass unchanged.

### 5d. FakeDocumentRepository update

`tests/unit/ingestion/_fakes.py` — add `mark_seen_in_sync` that records calls for assertion:

```python
class FakeDocumentRepository:
    def __init__(self) -> None:
        self.documents: list[Document] = []
        self.seen_in_sync_calls: list[tuple[UUID, UUID]] = []

    async def mark_seen_in_sync(self, document_id: UUID, sync_run_id: UUID) -> None:
        self.seen_in_sync_calls.append((document_id, sync_run_id))
```

---

## 6. RepositorySyncService — `lore/sync/service.py`

### 6a. Constructor change

Inject `DocumentRepository`:

```python
def __init__(
    self,
    registry: ConnectorRegistry,
    ingestion: IngestionService,
    ext_repo_repo: ExternalRepositoryRepository,
    sync_run_repo: RepositorySyncRunRepository,
    document_repo: DocumentRepository,   # NEW
) -> None:
    ...
    self._document_repo = document_repo
```

### 6b. Updated sync flow

```python
report = await self._ingestion.ingest_sync_result(
    sync_result, connector, sync_run_id=run.id  # NEW
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
```

Safety invariants:
- `mark_missing_github_files_inactive` is called only when `status == "succeeded"`.
- `mark_missing_github_files_inactive` is NOT called in the `except` block.
- Failed syncs leave all document active states untouched.
- Partial syncs leave all document active states untouched.

### 6c. Dependency wiring — `apps/api/routes/v1/repositories.py`

`doc_repo` is already created in `_build_sync_service`. Pass it to `RepositorySyncService`:

```python
def _build_sync_service(session, registry) -> RepositorySyncService:
    ...
    doc_repo = DocumentRepository(session)
    ...
    return RepositorySyncService(registry, ingestion, ext_repo_repo, sync_run_repo, doc_repo)
```

Check that `mark_finished` in `RepositorySyncRunRepository` already accepts `metadata`. If it does, pass `{"documents_marked_inactive": inactive_count}`. If not, do not expand the public API or response models for this PR — either add metadata support consistent with existing repository style, or skip `inactive_count` persistence.

---

## 7. RepositoryBriefService — `lore/artifacts/repository_brief_service.py`

One-line change in `generate_brief()`:

```python
# was:
paths = await self._document_repo.get_document_paths_by_repository_id(repository_id)
# becomes:
paths = await self._document_repo.get_active_document_paths_by_repository_id(repository_id)
```

No other changes. API contract and content schema are unchanged.

---

## 8. Document State Semantics

| State | is_active | deleted_at | Meaning |
|---|---|---|---|
| Active | true | NULL | File exists in current known state |
| Inactive | false | timestamp | File was seen before but not in a later succeeded sync |
| Reactivated | true | NULL (cleared) | File disappeared then reappeared in a later succeeded sync |

- `last_seen_sync_run_id`: updated on every `mark_seen_in_sync` call.
- `first_seen_sync_run_id`: set via COALESCE — never overwritten once set.
- Pre-existing documents: `first_seen_sync_run_id = NULL`, `last_seen_sync_run_id = NULL` until first tracked sync.

---

## 9. Tests

### File organization

| Tests | File |
|---|---|
| A–F: DocumentRepository integration | `tests/integration/test_document_active_state.py` (new) |
| G–K: Sync lifecycle (delete/fail/partial/reappear/unchanged) | `tests/integration/connectors/test_sync_document_lifecycle.py` (new) |
| L: Repository Brief excludes inactive | `tests/integration/test_repository_brief_active_documents.py` (new) |
| M: Migration 0005 adds fields with defaults | `tests/integration/test_migration_0005.py` (new) |
| Unit: unchanged file still calls mark_seen_in_sync | `tests/unit/ingestion/test_sync_run_tracking.py` (new) |

### Flexible connector for lifecycle tests (G–K)

Do not over-engineer. A simple mutable fake is sufficient:

```python
class MutableFakeConnector(BaseConnector):
    def __init__(self):
        self.files: list[RawExternalObject] = []
        self.warnings: list[str] = []

    async def full_sync(self, request):
        return SyncResult(
            connector_id="mutable-fake",
            raw_objects=self.files,
            warnings=self.warnings,
        )

    def normalize(self, raw):
        return GitHubNormalizer().normalize(raw)  # reuse existing normalizer
```

Tests then do:
```python
connector.files = [readme_raw, app_raw]
await sync_service.sync_repository(repo_id)

connector.files = [readme_raw]  # app.py gone
await sync_service.sync_repository(repo_id)

# assert app.py is inactive
```

### Test scenarios

**A.** Active `github.file` → `get_active_document_paths` returns it.  
**B.** Inactive `github.file` → `get_active_document_paths` excludes it.  
**C.** Active `github.repository` object → `get_active_document_paths` excludes it.  
**D.** `mark_seen_in_sync` on inactive doc → becomes active, `deleted_at=NULL`, both sync IDs set.  
**E.** `mark_seen_in_sync` on doc with existing `first_seen_sync_run_id` → `first_seen` preserved, `last_seen` updated.  
**F.** `mark_missing_github_files_inactive` with `last_seen=NULL` → doc becomes inactive (NULL-safe handling).  
**F2.** Already inactive doc is NOT updated by `mark_missing_github_files_inactive` — `deleted_at` preserves original timestamp.  
**G.** sync_1 succeeds (README + app.py) → sync_2 succeeds (README only) → app.py inactive, README active.  
**H.** sync_1 succeeds → sync_2 fails → both files remain active.  
**I.** sync_1 succeeds → sync_2 partial (warning, README only) → app.py remains active.  
**J.** sync_1→inactive app.py → sync_3 resyncs app.py → app.py active, `deleted_at=NULL`, `last_seen=sync_3.id`.  
**K.** sync_1 (README, hash X) → sync_2 (README, same hash X) → no new DocumentVersion, `last_seen=sync_2.id`.  
**L.** Brief for repo with active README.md + inactive deleted.py → `total_files=1`, deleted.py not in any stats.  
**M.** Migration 0005: `is_active` exists and defaults true; `deleted_at` nullable; sync ID columns nullable; pre-existing rows compatible.

---

## 10. Edge Cases

| Risk | Mitigation |
|---|---|
| `last_seen_sync_run_id = NULL` missed by `!=` | `or_(is_(None), != sync_run_id)` in WHERE |
| `mark_seen_in_sync` skipped for unchanged files | Called before checksum early-return |
| github.repository/issue/pr objects marked inactive | WHERE filters `object_type == "github.file"` |
| Already inactive docs get new `deleted_at` | WHERE filters `is_active.is_(True)` |
| Failed/partial sync marks deletions | Guarded by `if status == "succeeded"` |
| Import flow broken | `sync_run_id=None` remains valid; legacy path untouched |
| `rowcount` returns None | `result.rowcount or 0` |
