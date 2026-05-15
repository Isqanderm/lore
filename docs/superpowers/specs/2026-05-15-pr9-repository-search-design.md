# PR #9 — Repository Active Document Search v1

**Date:** 2026-05-15  
**Status:** Approved  
**Scope:** MVP lexical search over active documents with latest versions, repository-scoped.

---

## Goal

Add `POST /repositories/{repository_id}/search` — a minimal text search endpoint that finds relevant active documents by lexical scoring over path + latest version content.

**Not in scope:** embeddings, vector search, chunks, LLM answers, reranking, cross-repository search, Postgres full-text search, Elasticsearch.

---

## Architecture

```
apps/api/routes/v1/repositories.py
  └── POST /{repository_id}/search
        ↓ calls
lore/retrieval/service.py
  └── RetrievalService.search_repository(repository_id, query, limit)
        → RepositorySearchResultSet
        ↓ reads via
lore/infrastructure/db/repositories/document.py
  └── DocumentRepository.get_active_documents_with_latest_versions_by_repository_id(repository_id)
        → list[tuple[Document, DocumentVersion]]
        ↓ queries
DocumentORM + DocumentVersionORM + SourceORM + ExternalObjectORM
```

### Why this layering

- `lore/retrieval/service.py` is the designated home for retrieval logic per CLAUDE.md architecture.
- Router stays thin: validates request, checks repository exists, calls service, maps result to HTTP schema.
- Service returns domain dataclasses, not Pydantic schemas. This decouples retrieval logic from HTTP concerns.
- Repository exposes a dumb IO primitive. No scoring or ranking inside it.
- Scoring and snippet functions are pure Python — testable without DB.

### Critical: repository scope join-chain

`DocumentORM` has **no direct `repository_id` field**. Repository scope is resolved through:

```
DocumentORM.source_id
  → SourceORM.external_object_id
  → ExternalObjectORM.repository_id
```

This is the exact pattern used in the existing method:
`DocumentRepository.get_active_document_paths_by_repository_id()`

Any code that writes `DocumentORM.repository_id == repository_id` is wrong.

---

## New Files

| File | Purpose |
|---|---|
| `tests/unit/retrieval/__init__.py` | Package marker |
| `tests/unit/retrieval/test_search_scorer.py` | Unit tests for pure scoring/snippet functions |
| `tests/integration/test_repository_search.py` | Integration tests A–E via RetrievalService + real DB |
| `tests/e2e/test_repository_search_api.py` | E2E tests F–H + happy-path via HTTP |

## Modified Files

| File | Change |
|---|---|
| `lore/retrieval/service.py` | Replace placeholder with `RetrievalService` + domain types + pure functions |
| `lore/infrastructure/db/repositories/document.py` | Add `get_active_documents_with_latest_versions_by_repository_id` |
| `apps/api/routes/v1/repositories.py` | Add Pydantic schemas + `POST /{repository_id}/search` handler |

---

## API Contract

### Request

```
POST /api/v1/repositories/{repository_id}/search
```

```json
{
  "query": "github sync lifecycle",
  "limit": 10
}
```

### Response

```json
{
  "query": "github sync lifecycle",
  "results": [
    {
      "path": "lore/sync/service.py",
      "document_id": "...",
      "version_id": "...",
      "snippet": "...",
      "score": 0.71
    }
  ]
}
```

### Error cases

| Condition | HTTP status | Error code |
|---|---|---|
| Repository not found | 404 | (HTTPException) |
| Empty query (`""`) | 422 | Pydantic validation |
| Query too long (>500 chars) | 422 | Pydantic validation |
| Repository exists, no matches | 200 | — (empty `results`) |

**Important:** Repository non-existence must be detected explicitly via `ExternalRepositoryRepository.get_by_id()`, not inferred from an empty search result. These are semantically different states.

---

## Pydantic Schemas (router layer)

Defined in `apps/api/routes/v1/repositories.py`, following the existing pattern of inline schemas in routers:

```python
class RepositorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)

class RepositorySearchResult(BaseModel):
    path: str
    document_id: UUID
    version_id: UUID
    snippet: str
    score: float

class RepositorySearchResponse(BaseModel):
    query: str
    results: list[RepositorySearchResult]
```

---

## Domain Types (service layer)

Defined in `lore/retrieval/service.py` as frozen dataclasses. The service returns these — not Pydantic schemas. The router maps them:

```python
@dataclass(frozen=True)
class RetrievalHit:
    path: str
    document_id: UUID
    version_id: UUID
    snippet: str
    score: float

@dataclass(frozen=True)
class RepositorySearchResultSet:
    query: str
    results: list[RetrievalHit]
```

---

## `RetrievalService` class

Replace the placeholder `class RetrievalService: pass` in `lore/retrieval/service.py`:

```python
class RetrievalService:
    def __init__(
        self,
        document_repository: DocumentRepository,
        external_repository_repository: ExternalRepositoryRepository,
    ) -> None:
        ...

    async def search_repository(
        self,
        repository_id: UUID,
        query: str,
        limit: int,
    ) -> RepositorySearchResultSet:
        ...
```

**Service behaviour:**
1. Fetch all active documents with their latest version via repository method.
2. Tokenize query.
3. Score each (document, version) pair using `score_document()`.
4. Discard results where `score <= 0`.
5. Sort by `score DESC`, then `path ASC` as deterministic tie-break.
6. Apply limit.
7. Extract snippet per result using `extract_snippet()`.
8. Return `RepositorySearchResultSet`.

**Repository existence check belongs in the router**, which calls `ExternalRepositoryRepository.get_by_id()` before calling the service — following the pattern already used in `get_repository()`, `list_sync_runs()`, etc.

---

## `DocumentRepository` new method

```python
async def get_active_documents_with_latest_versions_by_repository_id(
    self, repository_id: UUID
) -> list[tuple[Document, DocumentVersion]]:
```

**Implementation:** One SQL query using a window function:

```sql
SELECT doc.*, dv.*
FROM documents doc
JOIN sources s ON doc.source_id = s.id
JOIN external_objects eo ON s.external_object_id = eo.id
JOIN (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY document_id
               ORDER BY version DESC, created_at DESC, id DESC
           ) AS rn
    FROM document_versions
) dv ON dv.document_id = doc.id AND dv.rn = 1
WHERE eo.repository_id = :repository_id
  AND eo.object_type = 'github.file'
  AND doc.is_active = true
```

Key points:
- INNER JOIN on versions: active documents without any document version are silently skipped (nothing to search).
- `ORDER BY version DESC, created_at DESC, id DESC` provides a deterministic latest-version selection even if version values collide.
- Filters both `is_active=True` and `object_type='github.file'`, consistent with existing methods.

---

## Pure Functions

Module-level in `lore/retrieval/service.py`. Do not split into separate files in this PR.

```python
def tokenize_query(query: str) -> list[str]:
    """Split query into lowercase tokens, minimum 2 chars."""
    return [
        token.lower()
        for token in re.split(r"\W+", query)
        if len(token) >= 2
    ]

def score_document(query: str, terms: list[str], path: str, content: str) -> float:
    """
    Lexical scoring: term frequency in path/content + phrase bonuses.
    Returns 0.0–1.0. Returns 0.0 if no terms match.
    """
    path_lower = path.lower()
    content_lower = content.lower()
    phrase = query.lower().strip()

    raw_score = 0.0

    for term in terms:
        if term in path_lower:
            raw_score += 3.0
        count = content_lower.count(term)
        raw_score += min(count, 10) * 1.0

    if phrase and phrase in path_lower:
        raw_score += 15.0
    if phrase and phrase in content_lower:
        raw_score += 10.0

    return min(raw_score / 20.0, 1.0)

def extract_snippet(content: str, terms: list[str], length: int = 240) -> str:
    """
    Extract a ~length-char snippet from content around the first matched term.
    Adds '...' prefix/suffix when truncated.
    Returns beginning of content if no term found.
    Returns '' if content is empty/None.
    """
```

---

## Router Handler

```python
@router.post("/{repository_id}/search", response_model=RepositorySearchResponse)
async def search_repository(
    repository_id: UUID,
    body: RepositorySearchRequest,
    session: SessionDep,
) -> RepositorySearchResponse:
    # 1. Check repository exists
    repo_repo = ExternalRepositoryRepository(session)
    repo = await repo_repo.get_by_id(repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    # 2. Build service and search
    doc_repo = DocumentRepository(session)
    svc = RetrievalService(
        document_repository=doc_repo,
        external_repository_repository=repo_repo,
    )
    result = await svc.search_repository(repository_id, body.query, body.limit)

    # 3. Map domain → API schema
    return RepositorySearchResponse(
        query=result.query,
        results=[
            RepositorySearchResult(
                path=hit.path,
                document_id=hit.document_id,
                version_id=hit.version_id,
                snippet=hit.snippet,
                score=hit.score,
            )
            for hit in result.results
        ],
    )
```

---

## Test Plan

### Unit tests — `tests/unit/retrieval/test_search_scorer.py`

`@pytest.mark.unit`

| Test | What it checks |
|---|---|
| `test_tokenize_splits_on_non_word` | `"github sync"` → `["github", "sync"]` |
| `test_tokenize_drops_short_tokens` | single-char tokens excluded |
| `test_score_zero_when_no_match` | no terms in path or content → 0.0 |
| `test_score_term_in_path` | term in path → score > 0 |
| `test_score_term_in_content` | term in content → score > 0 |
| `test_score_phrase_bonus_path` | phrase in path → higher than individual terms |
| `test_score_phrase_bonus_content` | phrase in content → higher than term-only |
| `test_score_clamped_to_one` | extreme content → score <= 1.0 |
| `test_snippet_centers_on_match` | snippet window around first match |
| `test_snippet_ellipsis_on_truncation` | `...` added when content truncated |
| `test_snippet_beginning_when_no_match` | returns first N chars if no term found |
| `test_snippet_empty_content` | returns `""` for empty/None content |

### Integration tests — `tests/integration/test_repository_search.py`

`@pytest.mark.integration` — use `db_session` fixture, seed ORM objects directly, call `RetrievalService.search_repository()`.

Seed helper shape follows existing `_seed_conn_and_repo()`, `_seed_ext_object()`, `_seed_source()`, `_seed_document()` patterns from `test_document_active_state.py`. Add `_seed_document_version(session, document, version, content)`.

| Test | Scenario |
|---|---|
| **A. Active only** | active doc matches + inactive doc has stronger match → only active returned |
| **B1. Latest version only — old has match** | old version has query, latest does not → doc not returned |
| **B2. Latest version only — latest has match** | old version no match, latest has query → doc returned with latest `version_id` |
| **C. Repository isolation** | repo A and repo B both have matching docs → search in A returns only A's docs |
| **D. Limit respected** | more matching docs than limit → exactly `limit` results returned |
| **E. Ranking** | doc B has phrase in path, doc A has weak content match → doc B ranked first |

### E2E tests — `tests/e2e/test_repository_search_api.py`

`@pytest.mark.e2e` — use `app_client_with_db` + `db_session` fixtures.

| Test | HTTP behaviour |
|---|---|
| **F. Empty query validation** | `POST` with `{"query": ""}` → 422 |
| **G. No results** | repo exists, no matching active docs → 200, `results: []` |
| **H. Repository not found** | unknown UUID → 404 |
| **I. Happy path** | seed repo + active doc + version with query text → 200, correct JSON shape (query, path, document_id, version_id, snippet, score present) |

Test I verifies: endpoint is correctly mounted, UUID fields serialize as strings, response schema matches contract.

---

## Non-Goals (explicit)

- No embeddings, vector search, pgvector, Elasticsearch
- No chunk-level search
- No LLM answer generation
- No cross-repository search
- No Postgres full-text search
- No separate `lore/search/` module
- No search backend abstraction
- No `current_version_id` field on DocumentORM
- No new DB migrations
- No permissions/ACL

---

## Definition of Done

- [ ] `POST /api/v1/repositories/{repository_id}/search` exists and is mounted
- [ ] Request validates `query` (1–500 chars) and `limit` (1–50, default 10)
- [ ] Response includes `query` + `results[]` with `path`, `document_id`, `version_id`, `snippet`, `score`
- [ ] Only `is_active=True` documents are searched
- [ ] Only the latest `DocumentVersion` (by `version DESC`) is searched per document
- [ ] Scope is strictly per-repository (join through `ExternalObjectORM.repository_id`)
- [ ] Results sorted by `score DESC`, tie-break `path ASC`
- [ ] Limit applied after sorting
- [ ] Empty query → 422
- [ ] Unknown repository → 404
- [ ] Repository with no matches → 200 `{ results: [] }`
- [ ] All unit, integration, and E2E tests pass
- [ ] `make lint` and `make type-check` pass
