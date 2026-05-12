# PR #5 — Repository Brief Artifact Foundation

**Date:** 2026-05-12  
**Status:** Approved  
**Branch target:** main

---

## 1. Goal

Build the first product-visible output for Lore: a deterministic, structured summary artifact (Repository Brief) generated from already-ingested repository data.

After this PR, a developer can:
1. Import a GitHub repository.
2. Sync it.
3. Call an endpoint to generate a repository brief.
4. See a deterministic repository overview.
5. Sync the repository again.
6. See the brief is stale.
7. Regenerate the brief and see it is fresh.

---

## 2. Non-goals

This PR does NOT include:

- LLM calls, prompt templates, embeddings, vector DB logic, semantic search.
- Repository architecture inference or code dependency analysis.
- Natural-language conclusions about code quality or design.
- Automatic brief regeneration after sync (explicit POST required).
- Deleted-file handling (see Known Limitations).
- Artifact history / multiple artifacts per repository.
- Background workers, webhook handling, scheduled sync.
- GitHub App installation flow, OAuth changes.
- Multi-provider abstraction beyond what already exists.
- partial sync run support for brief generation.

---

## 3. Existing Codebase Facts

Relevant facts discovered by codebase inspection:

- `RepositorySyncRunORM` exists with fields: `id`, `repository_id`, `status` (`running` / `succeeded` / `partial` / `failed`), `started_at`, `finished_at`, `connector_id`, counters, warnings.
- `ExternalRepositoryORM` exists with `last_synced_at` but no `current_sync_run_id`.
- `DocumentORM` has stable `path: str (NOT NULL)` and `logical_path: str | None`.
- One `DocumentORM` = one file. One `DocumentVersionORM` = one version of that file. `ChunkORM` = embedding chunk.
- `DocumentORM` links to repository via: `Document.source_id → Source.external_object_id → ExternalObject.repository_id`.
- `ExternalObjectORM.object_type` = `"github.file"` for file-backed documents.
- No artifact model exists yet.
- No soft-delete mechanism for documents exists in ingestion layer.
- Ingestion is find-or-create (idempotent on content hash). No removal of stale documents.

---

## 4. Data Model Changes

### New table: `repository_artifacts`

```sql
CREATE TABLE repository_artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id   UUID NOT NULL REFERENCES external_repositories(id),
    artifact_type   TEXT NOT NULL,
    title           TEXT NOT NULL,
    content_json    JSONB NOT NULL,
    source_sync_run_id UUID NOT NULL REFERENCES repository_sync_runs(id),
    generated_at    TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_repository_artifact_type UNIQUE (repository_id, artifact_type),
    CONSTRAINT ck_repository_artifact_type CHECK (artifact_type IN ('repository_brief'))
);

CREATE INDEX ix_repository_artifacts_repository_id ON repository_artifacts (repository_id);
CREATE INDEX ix_repository_artifacts_artifact_type ON repository_artifacts (artifact_type);
CREATE INDEX ix_repository_artifacts_source_sync_run_id ON repository_artifacts (source_sync_run_id);
```

`source_sync_run_id` is **NOT NULL**. A Repository Brief cannot exist without a sync run.

`content_json` has **no DEFAULT** — the service must always write a valid v1 JSON. An empty `{}` is not a valid Repository Brief.

`artifact_type` is constrained to known values via CHECK constraint. To add new artifact types in future PRs, extend the constraint via migration.

In Python, `artifact_type` values must be defined as constants (not raw strings at call sites):

```python
ARTIFACT_TYPE_REPOSITORY_BRIEF = "repository_brief"
```

Migration file: `migrations/versions/0004_repository_artifacts.py`

---

## 5. Repository Artifact Model

### ORM: `lore/infrastructure/db/models/repository_artifact.py`

Fields matching the table above. Standard SQLAlchemy 2.0 async pattern, same as existing models.

### Schema: `lore/schema/repository_artifact.py`

Frozen dataclass:

```python
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

### Repository: `lore/infrastructure/db/repositories/repository_artifact.py`

Methods:

```python
class RepositoryArtifactRepository(BaseRepository[RepositoryArtifactORM]):
    async def upsert(self, artifact: RepositoryArtifact) -> RepositoryArtifact
        # ON CONFLICT (repository_id, artifact_type) DO UPDATE
        # Updates: title, content_json, source_sync_run_id, generated_at, updated_at

    async def get_by_repository_and_type(
        self,
        repository_id: UUID,
        artifact_type: str,
    ) -> RepositoryArtifact | None
```

---

## 6. Sync State and Stale Detection

### Sync state anchor

`RepositorySyncRunORM.id` is the sync state anchor for freshness.

**Latest usable sync run** = the most recently finished sync run for a repository where `status = 'succeeded'`, ordered by `finished_at DESC NULLS LAST, started_at DESC`.

`partial` runs are **not used** for brief generation in PR #5. A partial run means some files may not have been processed successfully.

### Stale detection

```
is_stale = (artifact.source_sync_run_id != latest_succeeded_sync_run.id)
```

Computed dynamically at read time. No `status` field on `RepositoryArtifactORM`.

**Key trade-off (documented):** In PR #5, staleness is sync-run based, not content-diff based. Any new succeeded sync run makes the existing brief stale, even if the repository content did not change between syncs (e.g. same commit SHA). Content-equivalent sync optimization is out of scope.

### Edge cases

| Scenario | Behavior |
|---|---|
| No sync run exists | Cannot generate brief → HTTP 409 |
| Only `failed` sync runs exist | Cannot generate brief → HTTP 409 |
| Only `partial` sync runs exist | Cannot generate brief → HTTP 409 |
| `failed` sync after `succeeded` | Brief stays fresh (failed run is not the latest usable run) |
| New `succeeded` sync | Brief becomes stale (even if content unchanged) |
| Brief does not exist | GET returns `state: "missing"` |

### New repository method

```python
# lore/infrastructure/db/repositories/repository_sync_run.py

async def get_latest_succeeded_by_repository(
    self,
    repository_id: UUID,
) -> RepositorySyncRun | None:
    # WHERE status = 'succeeded'
    # ORDER BY finished_at DESC NULLS LAST, started_at DESC
    # LIMIT 1
```

---

## 7. Repository Brief Content Schema v1

`content_json` stored in `repository_artifacts.content_json`:

```json
{
  "schema_version": 1,
  "generated_by": "repository_brief_service",
  "repository": {
    "name": "lore",
    "full_name": "Isqanderm/lore",
    "provider": "github",
    "default_branch": "main",
    "url": "https://github.com/Isqanderm/lore"
  },
  "sync": {
    "sync_run_id": "...",
    "last_synced_at": "2026-05-12T10:00:00Z",
    "commit_sha": null
  },
  "stats": {
    "total_files": 123,
    "markdown_files": 4,
    "source_files": 88,
    "config_files": 12,
    "test_files": 9
  },
  "languages": [
    { "extension": ".ts", "count": 53 },
    { "extension": ".py", "count": 35 }
  ],
  "important_files": [
    { "path": "README.md", "kind": "readme" },
    { "path": "package.json", "kind": "package_manifest" },
    { "path": ".github/workflows/ci.yml", "kind": "ci_config" }
  ],
  "signals": {
    "has_readme": true,
    "has_tests": true,
    "has_docker": false,
    "has_ci": true,
    "has_package_manifest": true
  }
}
```

`schema_version` is included from the start so future content additions can be versioned without breakage.

### File categorization rules

**Markdown** (extension): `.md`, `.mdx`

**Source** (extension): `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.go`, `.java`, `.cs`, `.rs`, `.rb`, `.php`, `.cpp`, `.c`, `.h`, `.kt`, `.swift`

**Config** (filename or pattern, case-insensitive):
- `package.json`, `tsconfig.json`
- `vite.config.*`, `next.config.*`
- `eslint.*`, `prettier.*`
- `pyproject.toml`, `requirements.txt`, `poetry.lock`
- `dockerfile` (case-insensitive)
- `docker-compose.yml`, `docker-compose.yaml`
- `.env.example`
- `.github/workflows/*`

**Tests** (path or filename contains, case-insensitive):
- `test`, `tests`, `spec`, `__tests__`

A file may match multiple categories. Categories are counted independently (not mutually exclusive).

**Extensions** counted from all document paths. Returned sorted by count descending.

**Important files detection** (case-insensitive path matching):

| Pattern | kind |
|---|---|
| `readme.md`, `readme.rst`, `readme.txt`, `readme` | `readme` |
| `package.json` | `package_manifest` |
| `pyproject.toml` | `package_manifest` |
| `requirements.txt` | `package_manifest` |
| `dockerfile` | `docker` |
| `docker-compose.yml`, `docker-compose.yaml` | `docker` |
| `tsconfig.json` | `ts_config` |
| `eslint.*` | `lint_config` |
| `.env.example`, `.env.sample`, `.env.dist` | `env_example` |
| `.github/workflows/*` | `ci_config` |

**Signals** (derived from important_files):

```
has_readme         = any important_file.kind == "readme"
has_docker         = any important_file.kind == "docker"
has_ci             = any important_file.kind == "ci_config"
has_package_manifest = any important_file.kind == "package_manifest"
has_tests          = test_files > 0
```

---

## 8. RepositoryBriefService

**Location:** `lore/artifacts/repository_brief_service.py`  
**Models file:** `lore/artifacts/repository_brief_models.py`

The service reads from persisted repository/document/sync data only. It does NOT call GitHub directly.

### Method: `generate_brief(repository_id: UUID) → RepositoryBriefResponse`

1. Load `ExternalRepositoryORM` by `repository_id`. Raise 404 if not found.
2. Call `RepositorySyncRunRepository.get_latest_succeeded_by_repository(repository_id)`.
   - If `None` → raise 409 `repository_not_synced`.
3. Call `DocumentRepository.get_document_paths_by_repository_id(repository_id)` → `list[str]`.
4. Categorize paths using file categorization rules.
5. Build `content_json` dict with `schema_version: 1`.
   - `commit_sha` is always `null` in PR #5. `RepositorySyncRunORM` does not store the repository commit SHA, and using `DocumentVersionORM.version_ref` as a proxy is semantically unreliable (it represents a per-file ref, not a repo-level SHA). Stale detection is sync-run based, not commit-SHA based. Populating `commit_sha` is deferred until sync records it explicitly.
6. Upsert `RepositoryArtifact` via `RepositoryArtifactRepository.upsert()`.
   - `source_sync_run_id = latest_succeeded_run.id`
   - `generated_at = utcnow()`
7. Return `RepositoryBriefResponse` with `is_stale=False`, `state="fresh"`.

### Method: `get_brief(repository_id: UUID) → RepositoryBriefResponse`

1. Load `ExternalRepositoryORM`. Raise 404 if not found.
2. Load artifact: `RepositoryArtifactRepository.get_by_repository_and_type(repository_id, "repository_brief")`.
3. If no artifact: return `RepositoryBriefResponse(exists=False, state="missing")`.
4. Load `get_latest_succeeded_by_repository(repository_id)`.
5. Compute staleness:
   - If `latest_run` is `None` (all sync runs were failed/partial, or runs were deleted): `is_stale=True`, `current_sync_run_id=None`, `state="stale"`.
   - If `artifact.source_sync_run_id != latest_run.id`: `is_stale=True`, `state="stale"`.
   - Otherwise: `is_stale=False`, `state="fresh"`.
6. Return full `RepositoryBriefResponse`.

Idempotency: calling `generate_brief` twice in a row produces the same result and does not create duplicates (upsert on unique constraint).

---

## 9. DocumentRepository Query

**New method added to** `lore/infrastructure/db/repositories/document.py`:

```python
async def get_document_paths_by_repository_id(
    self,
    repository_id: UUID,
) -> list[str]:
    # SELECT DISTINCT d.path
    # FROM documents d
    # JOIN sources s ON d.source_id = s.id
    # JOIN external_objects eo ON s.external_object_id = eo.id
    # WHERE eo.repository_id = :repository_id
    #   AND eo.object_type = 'github.file'
    # ORDER BY d.path
```

**Constraint:** file statistics in repository brief must be based **only** on file-backed documents from GitHub, filtered through `ExternalObject.object_type = 'github.file'`. This prevents non-file objects (repository metadata, future issue/PR objects) from polluting file counts.

---

## 10. API Endpoints

**File:** `apps/api/routes/v1/repository_artifacts.py`  
**Mounted in:** `apps/api/main.py` at `/api/v1/repositories`

### `GET /api/v1/repositories/{repository_id}/brief`

Returns the current brief or missing state.

**Response when missing:**

```json
{
  "repository_id": "...",
  "artifact_type": "repository_brief",
  "exists": false,
  "state": "missing",
  "reason": "brief_not_generated"
}
```

**Response when fresh:**

```json
{
  "repository_id": "...",
  "artifact_type": "repository_brief",
  "exists": true,
  "state": "fresh",
  "is_stale": false,
  "generated_at": "2026-05-12T10:00:00Z",
  "source_sync_run_id": "...",
  "current_sync_run_id": "...",
  "brief": { ...content_json... }
}
```

**Response when stale:** same shape, `state: "stale"`, `is_stale: true`.

### `POST /api/v1/repositories/{repository_id}/brief/generate`

Generates or regenerates the repository brief. Always uses the latest succeeded sync run.

**Success response:** same shape as fresh GET response.

**Error responses:**

| Condition | HTTP | error.code |
|---|---|---|
| Repository not found | 404 | `repository_not_found` |
| No succeeded sync run exists | 409 | `repository_not_synced` |

Error format follows existing convention: `{"error": {"code": "...", "message": "..."}}`.

---

## 11. Error Handling

Follow existing convention in `apps/api/exception_handlers.py`:

- `RepositoryNotFoundError` → 404
- `RepositoryNotSyncedError` → 409 with `{"error": {"code": "repository_not_synced", "message": "Repository brief cannot be generated before a successful repository sync."}}`

---

## 12. Tests

### Unit tests: `tests/unit/artifacts/test_repository_brief_service.py`

All tests use mocked repositories — no DB.

- Generates brief for repository with zero files (empty stats, empty signals). Note: repository must have a succeeded sync run — "zero files" means the sync succeeded but ingested no file documents, not that no sync occurred.
- Counts markdown files correctly.
- Counts source files correctly.
- Counts config files correctly.
- Counts test files correctly (by path pattern).
- Detects important files (readme, package.json, dockerfile, ci config, env example).
- Detects extensions and returns sorted by count.
- Stores `source_sync_run_id` on generated artifact.
- Returns `is_stale=False` immediately after generation.
- Returns `is_stale=True` after repository sync state changes (new succeeded run).
- Regenerating brief makes it fresh again.
- `failed` sync run does not change freshness of brief (still fresh if last succeeded run unchanged).
- New succeeded sync with same repository content still makes brief stale (sync-run based, not content-based).
- Raises 409 if no succeeded sync run exists.
- Returns `state="stale"` with `current_sync_run_id=null` when artifact exists but no latest succeeded sync run found.
- Handles uppercase README.md detection.
- Handles nested paths like `docs/README.md`.
- Handles unsupported file extensions without error.

### Integration tests: `tests/integration/test_repository_artifact_repository.py`

- Creates artifact with correct fields.
- Upsert updates existing artifact, does not create duplicate.
- UNIQUE constraint on `(repository_id, artifact_type)` is enforced.
- `get_by_repository_and_type` returns `None` when no artifact exists.

### E2E tests: `tests/e2e/test_repository_brief_api.py`

- `GET /brief` returns `state: "missing"` when no brief exists.
- `POST /brief/generate` returns 409 when no succeeded sync run exists.
- `POST /brief/generate` creates brief with correct structure.
- `GET /brief` returns fresh brief after generation.
- `GET /brief` returns `state: "stale"` after a new succeeded sync run is recorded.
- `POST /brief/generate` again returns fresh.
- `GET /brief` on unknown repository_id returns 404.

---

## 13. Known Limitations

### Deleted files are not excluded from brief

The current ingestion layer does not remove or soft-delete `DocumentORM` records when files are deleted from GitHub. Therefore, the repository brief may include files that no longer exist in the upstream repository if they were present in a previous sync.

Handling deleted files is out of scope for this PR. When ingestion gains delete semantics, brief generation will automatically reflect them via the same `get_document_paths_by_repository_id` query.

### Staleness is sync-run based, not content-diff based

Any new succeeded sync run makes the existing brief stale, even if the repository content did not change between syncs (same commit SHA, no file modifications). Content-equivalent sync optimization is out of scope.

### partial sync runs are not used for brief generation

Only `succeeded` runs are considered. If all available sync runs are `partial` or `failed`, brief cannot be generated.

---

## 14. Manual Verification Flow

```bash
# 1. Import repository
POST /api/v1/repositories/import
{"url": "https://github.com/Isqanderm/lore", "connector_id": "github"}

# 2. Sync repository (or note: import already syncs)
POST /api/v1/repositories/{id}/sync

# 3. Generate brief
POST /api/v1/repositories/{id}/brief/generate
# → state: "fresh", is_stale: false

# 4. Read brief
GET /api/v1/repositories/{id}/brief
# → state: "fresh", is_stale: false

# 5. Trigger another sync
POST /api/v1/repositories/{id}/sync

# 6. Read brief again
GET /api/v1/repositories/{id}/brief
# → state: "stale", is_stale: true

# 7. Regenerate
POST /api/v1/repositories/{id}/brief/generate
# → state: "fresh", is_stale: false

# 8. Confirm fresh
GET /api/v1/repositories/{id}/brief
# → state: "fresh", is_stale: false
```

---

## 15. Acceptance Criteria

- [ ] Repository brief artifact can be generated without LLM.
- [ ] Brief is stored persistently in `repository_artifacts` table.
- [ ] Brief includes deterministic repository metadata, file stats, important files, languages/extensions, and basic signals.
- [ ] Brief records `source_sync_run_id` it was generated from.
- [ ] After a new succeeded sync run, existing brief is reported as stale.
- [ ] Regenerating brief makes it fresh.
- [ ] `POST /brief/generate` is idempotent — no duplicates.
- [ ] API returns `state: "missing"` when brief has never been generated.
- [ ] API returns 409 when generate is called with no succeeded sync run.
- [ ] Tests cover generation, stale detection, idempotency, and API behaviour.
- [ ] No LLM, embedding, semantic search, or agent logic introduced.
- [ ] `object_type = 'github.file'` filter is applied in document query.
- [ ] `schema_version: 1` is present in all generated briefs.
- [ ] Known limitations are documented in spec and code comments where relevant.
