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
- Service accepts only `DocumentRepository` — no knowledge of HTTP or repository existence. Repository existence check lives exclusively in the router.
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

**Any code that writes `DocumentORM.repository_id == repository_id` is wrong.**

---

## New Files

| File | Purpose |
|---|---|
| `tests/unit/retrieval/__init__.py` | Package marker |
| `tests/unit/retrieval/test_search_scorer.py` | Unit tests for pure scoring/snippet functions |
| `tests/integration/test_repository_search.py` | Integration tests via RetrievalService + real DB |
| `tests/e2e/test_repository_search_api.py` | E2E tests via HTTP |

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

| Condition | HTTP status |
|---|---|
| Repository not found | 404 |
| Empty or whitespace-only query | 422 |
| Query too long (>500 chars) | 422 |
| Repository exists, no matches | 200 (empty `results`) |

**Important:** Repository non-existence must be detected explicitly via `ExternalRepositoryRepository.get_by_id()`, not inferred from an empty search result. These are semantically different states.

---

## Pydantic Schemas (router layer)

Defined in `apps/api/routes/v1/repositories.py`, following the existing pattern of inline schemas in routers.

Project uses **Pydantic v2** — use `@field_validator` syntax.

```python
from pydantic import BaseModel, Field, field_validator

class RepositorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

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

The validator strips whitespace and rejects blank queries with 422. The stripped query is passed downstream.

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

Replace the placeholder `class RetrievalService: pass` in `lore/retrieval/service.py`.

`RetrievalService` accepts only `DocumentRepository`. It has no knowledge of `ExternalRepositoryRepository` — that check belongs exclusively in the router.

```python
class RetrievalService:
    def __init__(
        self,
        document_repository: DocumentRepository,
    ) -> None:
        self._document_repository = document_repository

    async def search_repository(
        self,
        repository_id: UUID,
        query: str,
        limit: int,
    ) -> RepositorySearchResultSet:
        ...
```

**Service behaviour:**
1. Fetch all active documents with their latest version via `document_repository.get_active_documents_with_latest_versions_by_repository_id(repository_id)`.
2. Tokenize query into terms with `tokenize_query(query)`.
3. Score each `(document, version)` pair with `score_document(query, terms, document.path, version.content)`.
4. Discard results where `score <= 0`.
5. Sort by `score DESC`, then `path ASC` as deterministic tie-break.
6. Apply `limit`.
7. Extract snippet per result with `extract_snippet(version.content, terms)`. Use the actual content field name from `DocumentVersion` domain model — if the field is not called `content`, use the real field name from the codebase.
8. Return `RepositorySearchResultSet`.

---

## `DocumentRepository` new method

```python
async def get_active_documents_with_latest_versions_by_repository_id(
    self, repository_id: UUID
) -> list[tuple[Document, DocumentVersion]]:
```

**SQLAlchemy implementation approach** — one query, window function via subquery:

```python
from sqlalchemy import func, select
from sqlalchemy import desc

# Step 1: subquery that selects the version_id of the latest version per document
latest_versions_subq = (
    select(
        DocumentVersionORM.id.label("version_id"),
        DocumentVersionORM.document_id.label("document_id"),
        func.row_number()
        .over(
            partition_by=DocumentVersionORM.document_id,
            order_by=(
                DocumentVersionORM.version.desc(),
                DocumentVersionORM.created_at.desc(),
                DocumentVersionORM.id.desc(),
            ),
        )
        .label("rn"),
    )
    .subquery()
)

# Step 2: main query — join documents to latest version ORM rows
stmt = (
    select(DocumentORM, DocumentVersionORM)
    .join(SourceORM, DocumentORM.source_id == SourceORM.id)
    .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
    .join(
        latest_versions_subq,
        latest_versions_subq.c.document_id == DocumentORM.id,
    )
    .join(
        DocumentVersionORM,
        DocumentVersionORM.id == latest_versions_subq.c.version_id,
    )
    .where(latest_versions_subq.c.rn == 1)
    .where(ExternalObjectORM.repository_id == repository_id)
    .where(ExternalObjectORM.object_type == _GITHUB_FILE_OBJECT_TYPE)
    .where(DocumentORM.is_active.is_(True))
)
```

Use the existing module-level constant `_GITHUB_FILE_OBJECT_TYPE = "github.file"` already defined in `document.py` — do not hardcode the string again. If the existing method `get_active_document_paths_by_repository_id()` applies the GitHub file object type filter differently, reuse that exact pattern. The goal is compatibility with current active document path logic, not just the constant itself.

Key points:
- INNER JOIN on versions: active documents without any `DocumentVersion` are silently skipped (nothing to search). This is not an error.
- The two-step subquery approach (`version_id` selection → join back to `DocumentVersionORM`) allows SQLAlchemy to correctly map full ORM instances into `list[tuple[Document, DocumentVersion]]`.
- `ORDER BY version DESC, created_at DESC, id DESC` is a deterministic tie-break even if version values collide.

---

## Pure Functions

Module-level in `lore/retrieval/service.py`. **Do not create separate scoring/snippet modules in this PR.**

`content` is typed as `str | None` in both functions because `DocumentVersion.content` may be null.

```python
import re

def tokenize_query(query: str) -> list[str]:
    """Split query into lowercase tokens, minimum 2 chars."""
    return [
        token.lower()
        for token in re.split(r"\W+", query)
        if len(token) >= 2
    ]


def score_document(
    query: str,
    terms: list[str],
    path: str,
    content: str | None,
) -> float:
    """
    Lexical scoring: term frequency in path/content + phrase bonuses.
    Returns 0.0–1.0. Returns 0.0 if no terms match.
    """
    path_lower = path.lower()
    content_lower = (content or "").lower()
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


def extract_snippet(
    content: str | None,
    terms: list[str],
    length: int = 240,
) -> str:
    """
    Extract a ~length-char snippet from content around the first matched term.
    Adds '...' prefix/suffix when truncated.
    Returns beginning of content if no term found.
    Returns '' if content is empty or None.
    """
    if not content:
        return ""
    content_lower = content.lower()
    half = length // 2

    for term in terms:
        idx = content_lower.find(term)
        if idx != -1:
            start = max(0, idx - half)
            end = min(len(content), start + length)
            # If we hit the end, shift start back to preserve target length.
            start = max(0, end - length)
            snippet = content[start:end]
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(content) else ""
            return prefix + snippet + suffix

    # No term found — return beginning
    snippet = content[:length]
    suffix = "..." if len(content) > length else ""
    return snippet + suffix
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
    svc = RetrievalService(document_repository=doc_repo)
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

`@pytest.mark.unit` — pure Python, no DB, no fixtures.

| Test name | What it checks |
|---|---|
| `test_tokenize_query_splits_on_non_word_chars` | `"github sync"` → `["github", "sync"]` |
| `test_tokenize_query_drops_single_char_tokens` | `"a b go"` → `["go"]` |
| `test_score_document_returns_zero_when_no_match` | unrelated path+content → `0.0` |
| `test_score_document_term_in_path_gives_positive_score` | term in path → score > 0 |
| `test_score_document_term_in_content_gives_positive_score` | term in content → score > 0 |
| `test_score_document_phrase_in_path_scores_higher_than_terms_only` | full phrase match in path > individual terms |
| `test_score_document_phrase_in_content_scores_higher_than_terms_only` | full phrase match in content > individual terms |
| `test_score_document_clamped_to_one` | extreme repetition → score never exceeds `1.0` |
| `test_score_document_none_content_treated_as_empty` | `content=None` → no crash, scores only path |
| `test_extract_snippet_centers_on_first_match` | snippet window is around matched term |
| `test_extract_snippet_adds_ellipsis_when_truncated` | `...` added on both sides when truncated |
| `test_extract_snippet_returns_beginning_when_no_term_match` | first 240 chars when no term found |
| `test_extract_snippet_returns_empty_for_none_content` | `content=None` → `""` |
| `test_extract_snippet_returns_empty_for_empty_string` | `content=""` → `""` |

### Integration tests — `tests/integration/test_repository_search.py`

`@pytest.mark.integration` — use `db_session` fixture, seed ORM objects directly, call `RetrievalService.search_repository()`.

Seed helpers follow the pattern from `test_document_active_state.py`:  
`_seed_conn_and_repo()`, `_seed_ext_object()`, `_seed_source()`, `_seed_document()`.  
Add: `_seed_document_version(session, document_orm, version_number, content)`.

| Test name | Scenario |
|---|---|
| `test_search_repository_excludes_inactive_documents` | active doc matches + inactive doc has stronger match → only active returned |
| `test_search_repository_skips_doc_when_only_old_version_matches` | old version has query, latest does not → doc not returned |
| `test_search_repository_uses_latest_document_version` | old version no match, latest has query → doc returned with latest `version_id` |
| `test_search_repository_scoped_to_target_repository` | repo A and repo B both match → search A returns only A's docs |
| `test_search_repository_respects_limit` | more matching docs than limit → exactly `limit` results |
| `test_search_repository_ranks_stronger_match_first` | doc B has phrase in path, doc A has weak content match → doc B ranked first |

### E2E tests — `tests/e2e/test_repository_search_api.py`

`@pytest.mark.e2e` — use `app_client_with_db` + `db_session` fixtures.

| Test name | HTTP behaviour |
|---|---|
| `test_search_repository_returns_422_for_empty_query` | `POST {"query": ""}` → 422 |
| `test_search_repository_returns_422_for_whitespace_query` | `POST {"query": "   "}` → 422 |
| `test_search_repository_returns_200_with_empty_results_when_no_match` | repo exists, no matching docs → 200, `results: []` |
| `test_search_repository_returns_404_for_unknown_repository` | unknown UUID → 404 |
| `test_search_repository_happy_path` | seed repo + active doc + version with query text → 200, full JSON shape validated |

`test_search_repository_happy_path` verifies: endpoint mounted correctly, UUID fields serialize as strings, all required fields present (`query`, `path`, `document_id`, `version_id`, `snippet`, `score`), `score` is a float.

---

## Non-Goals (explicit)

- No embeddings, vector search, pgvector, Elasticsearch
- No chunk-level search
- No LLM answer generation
- No cross-repository search
- No Postgres full-text search
- No separate `lore/search/` module
- No search backend abstraction layer
- No `current_version_id` field on `DocumentORM`
- No new DB migrations
- No permissions/ACL

---

## Pre-Implementation Checklist

Before writing any code, inspect:

- `DocumentORM` and `DocumentVersionORM` field names — verify `content` field name; use the actual codebase name, not this spec's assumption;
- `DocumentVersion` domain model field names (in `lore/schema/document.py`);
- `get_active_document_paths_by_repository_id()` implementation — reuse its join/filter pattern exactly;
- Existing route handler patterns in `repositories.py` for session management and 404 handling;
- Existing test seed helpers in `test_document_active_state.py` and `test_repository_brief_active_documents.py`.

Reuse existing constants and conventions. If a field name, object type literal, or join pattern in this spec differs from the actual codebase, use the actual codebase version.

---

## Definition of Done

- [ ] `POST /api/v1/repositories/{repository_id}/search` exists and is mounted
- [ ] Request validates `query` (1–500 chars, non-blank after strip) and `limit` (1–50, default 10)
- [ ] Response includes `query` + `results[]` with `path`, `document_id`, `version_id`, `snippet`, `score`
- [ ] Only `is_active=True` documents are searched
- [ ] Only the latest `DocumentVersion` (by `version DESC`) is searched per document
- [ ] Active documents without any version are silently skipped
- [ ] Scope is strictly per-repository (join through `ExternalObjectORM.repository_id`)
- [ ] Existing GitHub file object type filter is reused from document repository conventions — no new object type literal is introduced
- [ ] Results sorted by `score DESC`, tie-break `path ASC`
- [ ] Limit applied after sorting
- [ ] Empty or whitespace-only query → 422
- [ ] Unknown repository → 404
- [ ] Repository with no matches → 200 `{ results: [] }`
- [ ] All unit, integration, and E2E tests pass
- [ ] `make lint` and `make type-check` pass
