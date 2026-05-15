# PR #8 — Repository Structure Artifact: Design

**Date:** 2026-05-14
**Status:** Approved

---

## Goal

Add a deterministic artifact type `repository_structure` that describes the shape of a repository from active file paths only. No LLMs, no content parsing, no semantic analysis.

---

## Scope Constraints

**What this PR adds:**
- `ARTIFACT_TYPE_REPOSITORY_STRUCTURE = "repository_structure"` constant
- `RepositoryStructureContent` data model (pure dataclasses)
- Pure path-classification functions
- `RepositoryStructureService` following `RepositoryBriefService` pattern
- Migration 0006 expanding the check constraint
- Explicit GET/POST endpoints in `repository_artifacts.py`
- Unit + integration tests

**What this PR must NOT add:**
- LLMs, embeddings, semantic search
- Content parsing, AST parsing, dependency/call graph
- Auto-generation after import/sync
- Generic artifact abstraction (no base class, no generic router)
- Branch support, commit SHA tracking, background jobs, webhooks

---

## Architecture

### Pattern: Brief → Structure (copy, not abstract)

`repository_structure` is a parallel artifact type to `repository_brief`. Both are `RepositoryArtifact` rows with different `artifact_type` values. No shared base classes are introduced in this PR.

```
POST /structure/generate
  → RepositoryStructureService.generate_structure(repository_id)
      → load repo + latest succeeded sync run
      → get_active_document_paths_by_repository_id()
      → build deterministic RepositoryStructureContent from paths
      → upsert RepositoryArtifact(artifact_type="repository_structure")

GET /structure
  → RepositoryStructureService.get_structure(repository_id)
      → load artifact
      → compare source_sync_run_id vs latest succeeded run → fresh/stale
      → deserialize content
```

### Freshness model (same as Brief)

- `artifact.source_sync_run_id == latest_succeeded_run.id` → **fresh**
- `artifact.source_sync_run_id != latest_succeeded_run.id` → **stale**
- artifact does not exist → **missing**
- no latest succeeded run → **stale**

---

## Data Model

### New constant

```python
# lore/schema/repository_artifact.py
ARTIFACT_TYPE_REPOSITORY_STRUCTURE = "repository_structure"
```

### Content model (lore/artifacts/repository_structure_models.py)

Frozen dataclasses. Do NOT reuse `RepositoryBriefRepositoryInfo` / `RepositoryBriefSyncInfo`.

```python
RepositoryStructureRepositoryInfo  # name, full_name, provider, default_branch, url
RepositoryStructureSyncInfo        # sync_run_id, last_synced_at, commit_sha (None)
TopLevelDirectoryEntry             # path, files (count)
ManifestEntry                      # path, kind (e.g. "python.project")
EntrypointCandidate                # path, kind (e.g. "fastapi.app_candidate")
RepositoryStructureTree            # top_level_directories, top_level_files
RepositoryStructureClassification  # source_roots, test_roots, docs_roots, config_roots
RepositoryStructureInfrastructure  # docker_files, ci_files, migration_dirs
RepositoryStructureStats           # total_active_files, top_level_directory_count, manifest_count, entrypoint_candidate_count
RepositoryStructureContent         # all sections + schema_version=1, generated_by="repository_structure_service"
```

### Pure classification functions (same file)

| Function | Purpose |
|---|---|
| `normalize_path(path)` | Strip whitespace, strip leading `./`, preserve dot-dirs |
| `get_top_level_files(paths)` | Paths without `/`, sorted, distinct |
| `get_top_level_directories(paths)` | First segment of paths with `/`, count files, sorted |
| `detect_manifests(paths)` | Match basenames to 16 manifest kinds (pyproject.toml, package.json, etc.) |
| `detect_entrypoint_candidates(paths)` | Match paths to entry kinds; specific rules override generic |
| `detect_infrastructure(paths)` | Dockerfiles, CI config files, migration directories |
| `classify_roots(paths)` | Classify top-level dirs into source/test/docs/config |

**Entrypoint specificity rule:** `apps/api/main.py` → `fastapi.app_candidate`, NOT `python.main`.
Apply specific path-based rules before generic basename rules — check full path patterns first, then fall through to basename patterns.

**Path handling invariants:** deduplicate, ignore empty, sort all output lists, do not mutate input.

---

## Service (lore/artifacts/repository_structure_service.py)

```python
RepositoryStructureState = Literal["missing", "fresh", "stale"]

@dataclass(frozen=True)
class RepositoryStructureServiceResult:
    exists: bool
    state: RepositoryStructureState
    is_stale: bool
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    generated_at: datetime | None = None
    source_sync_run_id: UUID | None = None
    current_sync_run_id: UUID | None = None
    content: RepositoryStructureContent | None = None
    reason: str | None = None
```

**Constructor arguments:** same 4 repos as RepositoryBriefService:
- `external_repository_repo`
- `sync_run_repo`
- `document_repo`
- `artifact_repo`

**`generate_structure(repository_id)`:**
1. Load repo → `RepositoryNotFoundError` if missing
2. Load latest succeeded sync run → `RepositoryNotSyncedError` if missing
3. Load active paths via `document_repo.get_active_document_paths_by_repository_id`
4. Build `RepositoryStructureContent` from paths
5. Upsert `RepositoryArtifact(artifact_type="repository_structure", ...)`
6. Return `exists=True, state="fresh"`

**`get_structure(repository_id)`:**
1. Load repo → `RepositoryNotFoundError` if missing
2. Get artifact → return `exists=False, state="missing"` if not found
3. Load latest succeeded sync run
4. Determine freshness
5. Deserialize content via `_content_from_dict(d)`
6. Return result

**`_content_from_dict(d)`:** tolerant deserialization — use `.get()` with defaults for `schema_version` and `generated_by`; require core fields (`repository`, `sync`, `stats`).

---

## Migration 0006

**File:** `migrations/versions/0006_repository_structure_artifact_type.py`

```python
def upgrade() -> None:
    op.drop_constraint("ck_repository_artifact_type", "repository_artifacts", type_="check")
    op.create_check_constraint(
        "ck_repository_artifact_type",
        "repository_artifacts",
        "artifact_type IN ('repository_brief', 'repository_structure')",
    )

def downgrade() -> None:
    # Delete repository_structure rows first — otherwise restoring the old constraint will fail
    # because existing rows with artifact_type='repository_structure' violate the narrower constraint.
    op.execute("DELETE FROM repository_artifacts WHERE artifact_type = 'repository_structure'")
    op.drop_constraint("ck_repository_artifact_type", "repository_artifacts", type_="check")
    op.create_check_constraint(
        "ck_repository_artifact_type",
        "repository_artifacts",
        "artifact_type IN ('repository_brief')",
    )
```

Constraint name confirmed from 0004: `ck_repository_artifact_type`.

---

## API (apps/api/routes/v1/repository_artifacts.py)

Add alongside existing brief endpoints. Do not create a new route file.
Do not modify `apps/api/main.py` — `repository_artifacts_router` is already registered.

**Response models:**

```python
class RepositoryStructureMissingResponse(BaseModel):
    repository_id: UUID
    artifact_type: Literal["repository_structure"] = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    exists: bool = False
    state: Literal["missing"] = "missing"
    reason: str = "structure_not_generated"

class RepositoryStructurePresentResponse(BaseModel):
    repository_id: UUID
    artifact_type: Literal["repository_structure"] = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    exists: bool = True
    state: Literal["fresh", "stale"]
    is_stale: bool
    generated_at: datetime
    source_sync_run_id: UUID
    current_sync_run_id: UUID | None
    structure: dict[str, Any]
```

**Endpoints:**
- `GET /repositories/{repository_id}/structure`
- `POST /repositories/{repository_id}/structure/generate` (commits session after generation)

**Error handling:** Mirror existing Repository Brief endpoint behavior for `RepositoryNotFoundError` and `RepositoryNotSyncedError`. Do not introduce broad error-handling refactors in this PR — if brief endpoints already rely on global handlers, structure endpoints should do the same.

---

## Tests

### Unit: pure functions (tests/unit/artifacts/test_repository_structure_models.py)

Canonical test input:
```python
paths = [
    "README.md", "pyproject.toml", "Dockerfile",
    "lore/ingestion/service.py", "lore/sync/service.py",
    "tests/unit/test_service.py", "docs/index.md",
    ".github/workflows/ci.yml", "apps/api/main.py",
]
```

Required tests:
- `test_top_level_files_and_directories`
- `test_detect_manifests_root_and_nested`
- `test_detect_entrypoint_candidates_specificity` — verifies `apps/api/main.py` → `fastapi.app_candidate`
- `test_detect_infrastructure_files`
- `test_classify_roots`
- `test_empty_paths_returns_empty_sections`
- `test_duplicate_paths_are_deduplicated`
- `test_paths_are_sorted_deterministically`

### Unit: service (tests/unit/artifacts/test_repository_structure_service.py)

Reuse and extend fakes from `_fakes.py`. Required tests:
- `test_generate_structure_creates_artifact_from_active_paths`
- `test_get_structure_missing_returns_missing_state`
- `test_get_structure_fresh_when_source_sync_matches_latest`
- `test_get_structure_stale_when_latest_sync_differs`
- `test_generate_structure_raises_not_synced_without_successful_run`
- `test_generate_structure_raises_repository_not_found`

### Integration: migration (tests/integration/test_migration_0006.py)

- Verify `repository_structure` artifact type is accepted by the DB constraint
- Verify `repository_brief` is still accepted
- Use `RepositoryArtifactRepository.upsert()` as the practical test (not just information_schema)

### Integration: API lifecycle (tests/integration/test_repository_structure_api.py)

Fake connector: `provider="fake"`, `object_type="github.file"`, `connector_id="fake"`.
Paths: `README.md`, `pyproject.toml`, `apps/api/main.py`, `lore/ingestion/service.py`, `tests/unit/test_service.py`, `docs/index.md`, `.github/workflows/ci.yml`, `Dockerfile`.
`external_id = f"{owner}/{repo}:file:{path}"`, `raw.metadata["path"] = path`.

Required tests:
- **A.** `test_get_structure_missing_before_generation` — 200, exists=false, state="missing"
- **B.** `test_generate_structure_after_import` — 200, exists=true, state="fresh", structure.stats.total_active_files > 0
- **C.** `test_get_structure_fresh_after_generation` — exists=true, state="fresh", is_stale=false
- **D.** `test_structure_becomes_stale_after_new_successful_sync` — state="stale", current_sync_run_id != source_sync_run_id
- **E.** `test_structure_uses_only_active_documents` — Use `apps/api/main.py` as the file that gets removed in sync_2. sync_1: `README.md` + `apps/api/main.py`; generate structure → `entrypoint_candidates` contains `apps/api/main.py`. sync_2: `README.md` only; generate structure again → `apps/api/main.py` absent from `entrypoint_candidates`, `source_roots` may shrink. This proves inactive files are excluded from structural classification, not just the file count.
- **F.** `test_generate_structure_without_succeeded_sync_returns_error` — mirror behavior of the equivalent brief endpoint

---

## Files Changed

| File | Action |
|---|---|
| `lore/schema/repository_artifact.py` | Add `ARTIFACT_TYPE_REPOSITORY_STRUCTURE` |
| `lore/artifacts/repository_structure_models.py` | **New** — dataclasses + pure functions |
| `lore/artifacts/repository_structure_service.py` | **New** — service |
| `apps/api/routes/v1/repository_artifacts.py` | Add structure endpoints + response models |
| `migrations/versions/0006_repository_structure_artifact_type.py` | **New** — expand check constraint |
| `tests/unit/artifacts/test_repository_structure_models.py` | **New** |
| `tests/unit/artifacts/test_repository_structure_service.py` | **New** |
| `tests/unit/artifacts/_fakes.py` | Extend if needed |
| `tests/integration/test_migration_0006.py` | **New** |
| `tests/integration/test_repository_structure_api.py` | **New** |

`apps/api/main.py` — **do not modify**.

---

## Additional Implementation Clarifications

### detect_infrastructure: CI file detection

Do NOT use basename matching for `.circleci/config.yml`. Use path prefix matching:

```
ci_files:
- paths under ".github/workflows/" ending .yml or .yaml
- path == ".gitlab-ci.yml"
- paths under ".circleci/"
```

`basename(".circleci/config.yml")` returns `config.yml`, not `.circleci/config.yml` — basename matching here would be wrong.

### detect_entrypoint_candidates: rule priority

Always apply specific path-based rules before generic basename rules:
1. Check full path patterns first (`apps/api/main.py`, path ending `/api/main.py`, `cmd/<name>/main.go`, etc.)
2. Fall through to basename patterns only if no specific rule matched

This ensures `apps/api/main.py` resolves to `fastapi.app_candidate`, not `python.main`.

### Empty repository (zero active paths)

A repository with a succeeded sync and zero active paths is valid. `generate_structure` must succeed and return a fresh artifact with `total_active_files=0`. `RepositoryNotSyncedError` is raised only when there is no latest succeeded sync run, not when the active path list is empty.

### Active-only test (test E)

Use `apps/api/main.py` as the file that gets removed between syncs. Verify its absence from `entrypoint_candidates` (not just total count), proving structural classification — not just file counting — respects the active-only constraint.

### Error handling scope

Mirror existing Repository Brief endpoint behavior for `RepositoryNotFoundError` and `RepositoryNotSyncedError`. Do not refactor global error handling in this PR. If tests show that the existing brief endpoints work correctly due to global handlers, structure endpoints should rely on the same mechanism.

---

## Acceptance Criteria

1. `ARTIFACT_TYPE_REPOSITORY_STRUCTURE` constant exists
2. Migration 0006 allows `repository_structure` in DB constraint
3. `POST /structure/generate` works after successful import
4. `GET /structure` returns missing/fresh/stale correctly
5. Structure uses only active `github.file` documents
6. `source_sync_run_id` stored; freshness based on latest succeeded sync run
7. Content includes: repository info, sync info, tree, classification, manifests, entrypoint candidates, infrastructure, stats
8. Unit tests cover all pure classification functions
9. Service tests cover generate/get/stale/not-synced/not-found
10. API tests cover A–F scenarios including active-only behavior
11. No LLM, embedding, semantic search, content parsing, AST parsing, dependency graph, background worker, webhook, branch support, auto-generation introduced
