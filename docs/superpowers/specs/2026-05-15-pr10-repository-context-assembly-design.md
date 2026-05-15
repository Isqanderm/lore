# PR #10 — Repository Context Assembly v1

**Date:** 2026-05-15  
**Status:** Approved for implementation

---

## Goal

Add a repository-scoped context assembly endpoint that takes a natural-language query, reuses the PR #9 lexical ranking pipeline, and returns a ranked, budget-limited set of source excerpts from active documents with latest versions.

This PR prepares context for a future LLM answer endpoint. It must NOT generate an answer, call any LLM, use embeddings, or touch vector DB.

---

## Background

PR #9 added:
- `POST /api/v1/repositories/{repository_id}/search`
- `RetrievalService` in `lore/retrieval/service.py`
- `RetrievalService.search_repository(repository_id, query, limit)` — returns `RepositorySearchResultSet`
- `RetrievalHit(path, document_id, version_id, snippet, score)`
- `tokenize_query()`, `score_document()`, `extract_snippet()`
- `DocumentRepository.get_active_documents_with_latest_versions_by_repository_id()`
- Active-only, latest-version-only lexical search

PR #10 builds on this. Search logic is not duplicated.

---

## Endpoint

```
POST /api/v1/repositories/{repository_id}/context
```

**Request:**
```json
{
  "query": "github sync lifecycle",
  "limit": 8,
  "max_chars": 12000,
  "excerpt_chars": 2000
}
```

**Response:**
```json
{
  "query": "github sync lifecycle",
  "max_chars": 12000,
  "used_chars": 8340,
  "sources": [
    {
      "path": "lore/sync/service.py",
      "document_id": "...",
      "version_id": "...",
      "score": 0.71,
      "excerpt": "...",
      "excerpt_start": 1200,
      "excerpt_end": 2600
    }
  ]
}
```

---

## Architecture

### Chosen approach: private ranking helper (no second DB call)

`search_repository()` already loads full `version.content` via `get_active_documents_with_latest_versions_by_repository_id()` and then discards it, keeping only `snippet` in `RetrievalHit`. A second DB call to fetch content again would be wasteful.

Instead: extract a private `_rank_repository_document_versions()` helper. Both `search_repository()` and `build_repository_context()` call it. One DB call, no duplicated scoring logic, no constructor change to `RetrievalService`.

**Rejected alternatives:**
- Add `get_versions_by_ids()` to `DocumentVersionRepository` + second SELECT (spec default) — two DB calls for data already in memory
- Duplicate scoring logic inline in `build_repository_context()` — violates DRY

---

## Changes

### `lore/retrieval/service.py`

#### New module-level constant

```python
MIN_REMAINING_EXCERPT_CHARS = 300
```

#### New dataclasses

```python
@dataclass(frozen=True)
class _ScoredDocumentVersion:
    """Internal implementation detail — not part of the public retrieval API."""
    document: Document
    version: DocumentVersion
    score: float


@dataclass(frozen=True)
class ContextExcerpt:
    """Excerpt with character offsets into original content.

    Invariant: content[start:end] == text
    """
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class RepositoryContextSource:
    path: str
    document_id: UUID
    version_id: UUID
    score: float
    excerpt: str
    excerpt_start: int
    excerpt_end: int


@dataclass(frozen=True)
class RepositoryContextPackage:
    query: str
    max_chars: int
    used_chars: int
    sources: list[RepositoryContextSource]
```

#### New pure function `extract_context_excerpt()`

```python
def extract_context_excerpt(
    content: str | None,
    terms: list[str],
    max_chars: int,
) -> ContextExcerpt:
```

Behaviour:
- `max_chars <= 0` or `content` is `None`/empty → `ContextExcerpt(text="", start=0, end=0)`
- Finds the **earliest** character index across all matched terms (case-insensitive)
- If match found: centers window `[idx - half, idx - half + max_chars]`, clamped to content bounds
- If no match: `start=0`, `end=min(len(content), max_chars)`
- Invariant: `content[start:end] == text`, `end - start <= max_chars`
- Does **not** add `...` — this is not `extract_snippet()`

```python
def extract_context_excerpt(
    content: str | None,
    terms: list[str],
    max_chars: int,
) -> ContextExcerpt:
    if max_chars <= 0 or not content:
        return ContextExcerpt(text="", start=0, end=0)

    content_lower = content.lower()
    match_indexes = [
        idx
        for term in terms
        if term
        for idx in [content_lower.find(term)]
        if idx != -1
    ]

    if match_indexes:
        idx = min(match_indexes)
        half = max_chars // 2
        start = max(0, idx - half)
        end = min(len(content), start + max_chars)
        start = max(0, end - max_chars)
    else:
        start = 0
        end = min(len(content), max_chars)

    return ContextExcerpt(text=content[start:end], start=start, end=end)
```

#### Refactored `RetrievalService`

Existing `search_repository()` is refactored to use the new private helper. Public contract unchanged.

```python
class RetrievalService:
    def __init__(self, document_repository: DocumentRepository) -> None:
        self._document_repository = document_repository

    async def _rank_repository_document_versions(
        self,
        repository_id: UUID,
        query: str,
        limit: int,
    ) -> list[_ScoredDocumentVersion]:
        pairs = await self._document_repository \
            .get_active_documents_with_latest_versions_by_repository_id(repository_id)
        terms = tokenize_query(query)
        scored: list[_ScoredDocumentVersion] = []
        for doc, version in pairs:
            s = score_document(query, terms, doc.path, version.content)
            if s > 0:
                scored.append(_ScoredDocumentVersion(document=doc, version=version, score=s))
        scored.sort(key=lambda item: (-item.score, item.document.path))
        return scored[:limit]

    async def search_repository(
        self,
        repository_id: UUID,
        query: str,
        limit: int,
    ) -> RepositorySearchResultSet:
        ranked = await self._rank_repository_document_versions(repository_id, query, limit)
        terms = tokenize_query(query)
        hits = [
            RetrievalHit(
                path=item.document.path,
                document_id=item.document.id,
                version_id=item.version.id,
                snippet=extract_snippet(item.version.content, terms),
                score=item.score,
            )
            for item in ranked
        ]
        return RepositorySearchResultSet(query=query, results=hits)

    async def build_repository_context(
        self,
        repository_id: UUID,
        query: str,
        limit: int,
        max_chars: int,
        excerpt_chars: int,
    ) -> RepositoryContextPackage:
        if max_chars <= 0 or excerpt_chars <= 0:
            return RepositoryContextPackage(
                query=query, max_chars=max_chars, used_chars=0, sources=[]
            )

        ranked = await self._rank_repository_document_versions(repository_id, query, limit)
        terms = tokenize_query(query)
        used = 0
        sources: list[RepositoryContextSource] = []

        for item in ranked:
            remaining = max_chars - used
            if remaining < MIN_REMAINING_EXCERPT_CHARS:
                break
            per_source = min(excerpt_chars, remaining)
            excerpt = extract_context_excerpt(item.version.content, terms, per_source)
            if not excerpt.text:
                continue
            sources.append(RepositoryContextSource(
                path=item.document.path,
                document_id=item.document.id,
                version_id=item.version.id,
                score=item.score,
                excerpt=excerpt.text,
                excerpt_start=excerpt.start,
                excerpt_end=excerpt.end,
            ))
            used += len(excerpt.text)

        return RepositoryContextPackage(
            query=query, max_chars=max_chars, used_chars=used, sources=sources
        )
```

`used_chars` counts only `len(excerpt.text)` — no JSON overhead, paths, UUIDs, or scores.

Note: `tokenize_query(query)` is called twice in `search_repository()` — once inside `_rank_repository_document_versions()` and once for `extract_snippet()`. Same in `build_repository_context()`. This is intentional and acceptable: `tokenize_query` is a pure function with no IO, and keeping the calls explicit makes each method self-contained. Do not try to thread `terms` as a parameter through `_rank_repository_document_versions()` to avoid this — it would complicate the private helper's signature for negligible gain.

---

### `apps/api/routes/v1/repositories.py`

#### New imports

```python
from typing import TYPE_CHECKING, Annotated, Self
from pydantic import BaseModel, Field, field_validator, model_validator
```

#### New schemas (inline, following PR #9 style)

```python
class RepositoryContextRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)
    max_chars: int = Field(default=12000, ge=1000, le=50000)
    excerpt_chars: int = Field(default=2000, ge=300, le=10000)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    @model_validator(mode="after")
    def excerpt_must_not_exceed_budget(self) -> Self:
        if self.excerpt_chars > self.max_chars:
            raise ValueError("excerpt_chars must be <= max_chars")
        return self


class RepositoryContextSource(BaseModel):
    path: str
    document_id: UUID
    version_id: UUID
    score: float
    excerpt: str
    excerpt_start: int
    excerpt_end: int


class RepositoryContextResponse(BaseModel):
    query: str
    max_chars: int
    used_chars: int
    sources: list[RepositoryContextSource]
```

Note: `RepositoryContextSource` is a Pydantic response schema defined inline in the router. The service layer also has a `RepositoryContextSource` dataclass in `lore/retrieval/service.py` — same name, different module. There is no import collision because the router does **not** import `RepositoryContextSource` from `lore.retrieval.service` by name. It only imports `RetrievalService`. The service dataclass is accessed solely as an attribute of the `RepositoryContextPackage` return value (`result.sources[i].path`, etc.) — never via a direct import into the router namespace.

#### New endpoint

```python
@router.post("/{repository_id}/context", response_model=RepositoryContextResponse)
async def build_repository_context(
    repository_id: UUID,
    body: RepositoryContextRequest,
    session: SessionDep,
) -> RepositoryContextResponse:
    repo_repo = ExternalRepositoryRepository(session)
    if await repo_repo.get_by_id(repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    svc = RetrievalService(document_repository=DocumentRepository(session))
    result = await svc.build_repository_context(
        repository_id=repository_id,
        query=body.query,
        limit=body.limit,
        max_chars=body.max_chars,
        excerpt_chars=body.excerpt_chars,
    )

    return RepositoryContextResponse(
        query=result.query,
        max_chars=result.max_chars,
        used_chars=result.used_chars,
        sources=[
            RepositoryContextSource(
                path=s.path,
                document_id=s.document_id,
                version_id=s.version_id,
                score=s.score,
                excerpt=s.excerpt,
                excerpt_start=s.excerpt_start,
                excerpt_end=s.excerpt_end,
            )
            for s in result.sources
        ],
    )
```

No `session.commit()` — read-only endpoint.

---

## Tests

### Unit — `tests/unit/retrieval/test_context_excerpt.py`

New file, `pytestmark = pytest.mark.unit`.

| Test | Verifies |
|------|----------|
| `test_extract_context_excerpt_none_content` | returns `ContextExcerpt("", 0, 0)` |
| `test_extract_context_excerpt_empty_content` | same for `""` |
| `test_extract_context_excerpt_max_chars_zero` | defensive guard → empty |
| `test_extract_context_excerpt_returns_beginning_when_no_term_match` | `start == 0` |
| `test_extract_context_excerpt_centers_on_matched_term` | term present in `excerpt.text` |
| `test_extract_context_excerpt_uses_earliest_term_match` | chooses earliest occurrence across terms, not first term in list |
| `test_extract_context_excerpt_offset_invariant` | `content[start:end] == text` |
| `test_extract_context_excerpt_never_exceeds_max_chars` | `end - start <= max_chars` and `len(text) <= max_chars` |

Earliest-match test example:
```python
def test_extract_context_excerpt_uses_earliest_term_match() -> None:
    content = "aaa second " + "x" * 100 + " first"
    excerpt = extract_context_excerpt(content, ["first", "second"], max_chars=40)
    assert "second" in excerpt.text
    assert excerpt.start <= content.index("second")
```

### Integration — `tests/integration/test_repository_context.py`

New file, `pytestmark = pytest.mark.integration`. Seed helpers copied locally from `test_repository_search.py` — no shared factory infrastructure introduced in this PR.

| Test | Verifies |
|------|----------|
| `test_context_respects_max_chars` | `result.used_chars <= max_chars` |
| `test_context_respects_excerpt_chars_per_source` | `len(s.excerpt) <= excerpt_chars` for each source |
| `test_context_preserves_ranking_order` | order matches score ranking (deterministic: strong doc has phrase in path + many content hits; weak doc has one content hit) |
| `test_context_skips_inactive_documents` | inactive doc absent from sources |
| `test_context_uses_latest_version_only` | `source.version_id` matches latest version |
| `test_context_includes_all_fields` | `document_id`, `version_id`, `path`, `score` all present |
| `test_context_returns_empty_sources_when_no_match` | `sources == []`, `used_chars == 0` |
| `test_context_used_chars_matches_sum_of_excerpts` | `used_chars == sum(len(s.excerpt) for s in sources)` |
| `test_context_offset_invariant_in_service_output` | `latest_content[s.excerpt_start:s.excerpt_end] == s.excerpt` |

### E2E — `tests/e2e/test_repository_context_api.py`

New file, `pytestmark = pytest.mark.e2e`. Seed helpers copied locally.

| Test | HTTP |
|------|------|
| Happy path | 200; `query`, `max_chars`, `used_chars`, `sources` present; first source has all 7 fields |
| Unknown repository | 404 |
| Empty query | 422 |
| Whitespace-only query | 422 |
| `max_chars` out of range (e.g. 500) | 422 |
| `excerpt_chars` out of range (e.g. 100) | 422 |
| `excerpt_chars > max_chars` (e.g. `{"max_chars": 1000, "excerpt_chars": 1200}`) | 422 from `model_validator` |
| No matches | 200, `sources: []`, `used_chars: 0` |

---

## Non-goals

Not in this PR:
- LLM answer generation, prompt templates, OpenAI/Anthropic client
- Embeddings, vector DB, pgvector, Elasticsearch
- Chunk model or chunk-level retrieval
- BM25, semantic search, reranking
- Citations as generated prose
- Line numbers
- Tokenizer-based token budgeting
- Cross-repository context
- GitHub issues/PR context
- Permissions/ACL
- New DB migrations
- Shared test factory infrastructure

---

## Definition of Done

- `POST /api/v1/repositories/{repository_id}/context` exists and is mounted
- Request validates `query`, `limit`, `max_chars`, `excerpt_chars`; `excerpt_chars > max_chars` returns 422
- Repository existence check returns 404 for unknown repository
- Response contains `query`, `max_chars`, `used_chars`, `sources`
- Each source contains `path`, `document_id`, `version_id`, `score`, `excerpt`, `excerpt_start`, `excerpt_end`
- Context reuses ranking pipeline from PR #9 via `_rank_repository_document_versions()`
- Active-only, latest-version-only — inherited from underlying search
- Ranking order preserved from `_rank_repository_document_versions()`
- `used_chars == sum(len(s.excerpt) for s in sources)` and never exceeds `max_chars`
- `content[s.excerpt_start:s.excerpt_end] == s.excerpt` for every source
- Each `len(s.excerpt) <= excerpt_chars` (or `<= remaining` when budget is tight)
- No matches → 200, `sources: []`, `used_chars: 0`
- No LLM, embeddings, chunks, vector search
- Unit, integration, e2e tests pass
- `make lint` and `make type-check` pass
