# PR #10 — Repository Context Assembly v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/v1/repositories/{id}/context` that returns a ranked, budget-limited set of source excerpts from active latest-version documents, without any LLM, embeddings, or vector search.

**Architecture:** Extract `_rank_repository_document_versions()` private helper from the existing `search_repository()` scoring logic so both `/search` and `/context` share one DB call. Add `extract_context_excerpt()` pure function with offset tracking. All budget assembly logic lives in `RetrievalService.build_repository_context()`. Router stays thin.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2 (`model_validator`, `Self`), SQLAlchemy async, pytest-asyncio. No new packages, no new migrations.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `lore/retrieval/service.py` | Modify | Add constant, dataclasses, `extract_context_excerpt()`, `_ScoredDocumentVersion`, `_rank_repository_document_versions()`, `build_repository_context()`; refactor `search_repository()` |
| `apps/api/routes/v1/repositories.py` | Modify | Add `RepositoryContextRequest`, `RepositoryContextSource`, `RepositoryContextResponse` schemas and `POST /{repository_id}/context` endpoint |
| `tests/unit/retrieval/test_context_excerpt.py` | Create | Unit tests for `extract_context_excerpt()` |
| `tests/integration/test_repository_context.py` | Create | Integration tests for `RetrievalService.build_repository_context()` |
| `tests/e2e/test_repository_context_api.py` | Create | E2E HTTP tests for the new endpoint |

`RetrievalService.__init__` signature does **not** change. No new packages. No migrations.

---

## Task 1: Dataclasses + `extract_context_excerpt()` — TDD

**Files:**
- Create: `tests/unit/retrieval/test_context_excerpt.py`
- Modify: `lore/retrieval/service.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/retrieval/test_context_excerpt.py`:

```python
from __future__ import annotations

import pytest

from lore.retrieval.service import ContextExcerpt, extract_context_excerpt

pytestmark = pytest.mark.unit


def test_extract_context_excerpt_none_content() -> None:
    result = extract_context_excerpt(None, ["term"], max_chars=100)
    assert result == ContextExcerpt(text="", start=0, end=0)


def test_extract_context_excerpt_empty_content() -> None:
    result = extract_context_excerpt("", ["term"], max_chars=100)
    assert result == ContextExcerpt(text="", start=0, end=0)


def test_extract_context_excerpt_max_chars_zero() -> None:
    result = extract_context_excerpt("some content here", ["content"], max_chars=0)
    assert result == ContextExcerpt(text="", start=0, end=0)


def test_extract_context_excerpt_returns_beginning_when_no_term_match() -> None:
    content = "hello world " * 20
    result = extract_context_excerpt(content, ["notfound"], max_chars=40)
    assert result.start == 0
    assert result.text == content[:40]


def test_extract_context_excerpt_centers_on_matched_term() -> None:
    content = "a" * 200 + "TARGET" + "b" * 200
    result = extract_context_excerpt(content, ["target"], max_chars=100)
    assert "TARGET" in result.text


def test_extract_context_excerpt_uses_earliest_term_match() -> None:
    content = "aaa second " + "x" * 100 + " first"
    result = extract_context_excerpt(content, ["first", "second"], max_chars=40)
    assert "second" in result.text
    assert result.start <= content.index("second")


def test_extract_context_excerpt_offset_invariant() -> None:
    content = "prefix " * 50 + "needle" + " suffix" * 50
    result = extract_context_excerpt(content, ["needle"], max_chars=200)
    assert content[result.start:result.end] == result.text


def test_extract_context_excerpt_never_exceeds_max_chars() -> None:
    content = "x" * 1000
    result = extract_context_excerpt(content, ["x"], max_chars=200)
    assert result.end - result.start <= 200
    assert len(result.text) <= 200
```

- [ ] **Step 2: Run tests — verify FAIL**

```bash
pytest tests/unit/retrieval/test_context_excerpt.py -v
```

Expected: `ImportError` — `ContextExcerpt` and `extract_context_excerpt` not yet defined.

- [ ] **Step 3: Add constant, dataclasses, and pure function to `lore/retrieval/service.py`**

Open `lore/retrieval/service.py`. The file already has `from __future__ import annotations` at the top — do not remove it. It is required for `_ScoredDocumentVersion` (added in Task 2) to use `Document` and `DocumentVersion` as annotations without a circular import.

After the `RepositorySearchResultSet` dataclass (line ~25) and before `tokenize_query`, insert:

```python
MIN_REMAINING_EXCERPT_CHARS = 300


@dataclass(frozen=True)
class ContextExcerpt:
    """Excerpt with character offsets into original content.

    Invariant: content[start:end] == text
    """

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ContextSourceItem:
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
    sources: list[ContextSourceItem]
```

After `extract_snippet()` (end of the function block), insert:

```python
def extract_context_excerpt(
    content: str | None,
    terms: list[str],
    max_chars: int,
) -> ContextExcerpt:
    if max_chars <= 0 or not content:
        return ContextExcerpt(text="", start=0, end=0)

    content_lower = content.lower()
    match_indexes: list[int] = []
    for term in terms:
        if not term:
            continue
        idx = content_lower.find(term)
        if idx != -1:
            match_indexes.append(idx)

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

- [ ] **Step 4: Run tests — verify PASS**

```bash
pytest tests/unit/retrieval/test_context_excerpt.py -v
```

Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add lore/retrieval/service.py tests/unit/retrieval/test_context_excerpt.py
git commit -m "feat: add ContextExcerpt, ContextSourceItem, RepositoryContextPackage, extract_context_excerpt"
```

---

## Task 2: Refactor `search_repository()` to Use Private Helper

**Files:**
- Modify: `lore/retrieval/service.py`

The existing `search_repository()` inlines scoring and ranking. This task extracts `_rank_repository_document_versions()` so `build_repository_context()` can reuse it without a second DB call. Public contract of `search_repository()` is unchanged.

- [ ] **Step 1: Run existing search tests — verify they pass before refactor**

```bash
pytest tests/unit/retrieval/test_search_scorer.py tests/integration/test_repository_search.py -v
```

Expected: all pass. If any fail, stop and investigate before touching the code.

- [ ] **Step 2: Add `_ScoredDocumentVersion` dataclass and `_rank_repository_document_versions()` private method**

In `lore/retrieval/service.py`, directly before `class RetrievalService:` (after all module-level functions), insert:

```python
@dataclass(frozen=True)
class _ScoredDocumentVersion:
    """Internal implementation detail — not part of the public retrieval API."""

    document: Document
    version: DocumentVersion
    score: float
```

Replace **only** the class body starting from `class RetrievalService:` to the end of that class. Do **not** remove module-level dataclasses or functions added in Task 1 (`ContextExcerpt`, `ContextSourceItem`, `RepositoryContextPackage`, `MIN_REMAINING_EXCERPT_CHARS`, `extract_context_excerpt`).

```python
class RetrievalService:
    def __init__(
        self,
        document_repository: DocumentRepository,
    ) -> None:
        self._document_repository = document_repository

    async def _rank_repository_document_versions(
        self,
        repository_id: UUID,
        query: str,
        limit: int,
    ) -> list[_ScoredDocumentVersion]:
        pairs: list[
            tuple[Document, DocumentVersion]
        ] = await self._document_repository.get_active_documents_with_latest_versions_by_repository_id(
            repository_id
        )
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
```

Note: `tokenize_query(query)` is called once inside `_rank_repository_document_versions()` and again in `search_repository()` for `extract_snippet()`. This is intentional — `tokenize_query` is a pure function with no IO. Do not thread `terms` through the private helper signature.

- [ ] **Step 3: Run existing search tests — verify they still pass**

```bash
pytest tests/unit/retrieval/test_search_scorer.py tests/integration/test_repository_search.py -v
```

Expected: all pass. If any fail, the refactor introduced a regression — fix before proceeding.

- [ ] **Step 4: Commit**

```bash
git add lore/retrieval/service.py
git commit -m "refactor: extract _rank_repository_document_versions from search_repository"
```

---

## Task 3: `build_repository_context()` + Integration Tests — TDD

**Files:**
- Create: `tests/integration/test_repository_context.py`
- Modify: `lore/retrieval/service.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/integration/test_repository_context.py`:

```python
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.retrieval.service import RetrievalService

pytestmark = pytest.mark.integration


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_conn_and_repo(session: AsyncSession) -> ExternalRepositoryORM:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:8]
    conn = ExternalConnectionORM(
        id=uuid4(),
        provider="github",
        auth_mode="env_pat",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(conn)
    await session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(),
        connection_id=conn.id,
        provider="github",
        owner=f"ctxorg-{suffix}",
        name=f"ctxrepo-{suffix}",
        full_name=f"ctxorg-{suffix}/ctxrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/ctxorg-{suffix}/ctxrepo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(repo)
    await session.flush()
    return repo


async def _seed_file_doc(
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    path: str,
    is_active: bool = True,
) -> DocumentORM:
    now = datetime.now(UTC)
    eo = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=repo.connection_id,
        provider="github",
        object_type="github.file",
        external_id=f"{repo.full_name}:file:{path}:{uuid4().hex[:6]}",
        raw_payload_json={},
        raw_payload_hash="hash-" + uuid4().hex[:8],
        fetched_at=now,
        metadata_={},
    )
    session.add(eo)
    await session.flush()

    src = SourceORM(
        id=uuid4(),
        source_type_raw="github.file",
        source_type_canonical="github.file",
        origin=f"https://github.com/{repo.full_name}/blob/main/{path}",
        external_object_id=eo.id,
        created_at=now,
        updated_at=now,
    )
    session.add(src)
    await session.flush()

    doc = DocumentORM(
        id=uuid4(),
        source_id=src.id,
        title=path,
        path=path,
        is_active=is_active,
        deleted_at=None if is_active else now,
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(doc)
    await session.flush()
    return doc


async def _seed_version(
    session: AsyncSession,
    doc: DocumentORM,
    version: int,
    content: str,
) -> DocumentVersionORM:
    now = datetime.now(UTC)
    dv = DocumentVersionORM(
        id=uuid4(),
        document_id=doc.id,
        version=version,
        content=content,
        checksum=hashlib.sha256(content.encode()).hexdigest(),
        created_at=now,
        metadata_={},
    )
    session.add(dv)
    await session.flush()
    return dv


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_context_respects_max_chars(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    content = "sync lifecycle management " * 100  # ~2500 chars
    for i in range(5):
        doc = await _seed_file_doc(db_session, repo, f"budget_ctx_{i}.py", is_active=True)
        await _seed_version(db_session, doc, 1, content)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=800,
        excerpt_chars=400,
    )
    assert result.used_chars <= 800
    assert result.used_chars == sum(len(s.excerpt) for s in result.sources)


async def test_context_respects_excerpt_chars_per_source(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    content = "sync lifecycle management " * 200  # ~5000 chars
    for i in range(3):
        doc = await _seed_file_doc(db_session, repo, f"excerpt_limit_ctx_{i}.py", is_active=True)
        await _seed_version(db_session, doc, 1, content)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=3,
        max_chars=5000,
        excerpt_chars=500,
    )
    assert len(result.sources) > 0
    for source in result.sources:
        assert len(source.excerpt) <= 500


async def test_context_preserves_ranking_order(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)

    # Strong: phrase in path + many content hits → score = 1.0
    strong = await _seed_file_doc(
        db_session, repo, "sync-lifecycle/rank_manager.py", is_active=True
    )
    await _seed_version(db_session, strong, 1, "sync lifecycle " * 20)

    # Weak: one content hit only → score < 1.0
    weak = await _seed_file_doc(db_session, repo, "rank_utils.py", is_active=True)
    await _seed_version(db_session, weak, 1, "sync lifecycle mentioned once")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=10,
        max_chars=10000,
        excerpt_chars=2000,
    )
    assert len(result.sources) >= 2
    paths = [s.path for s in result.sources]
    assert paths.index("sync-lifecycle/rank_manager.py") < paths.index("rank_utils.py")


async def test_context_skips_inactive_documents(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)

    active = await _seed_file_doc(db_session, repo, "active_ctx_doc.py", is_active=True)
    await _seed_version(db_session, active, 1, "sync lifecycle active content")

    inactive = await _seed_file_doc(db_session, repo, "inactive_ctx_doc.py", is_active=False)
    await _seed_version(db_session, inactive, 1, "sync lifecycle " * 20)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=10,
        max_chars=10000,
        excerpt_chars=1000,
    )
    paths = [s.path for s in result.sources]
    assert "active_ctx_doc.py" in paths
    assert "inactive_ctx_doc.py" not in paths


async def test_context_uses_latest_version_only(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "versioned_ctx_doc.py", is_active=True)
    await _seed_version(db_session, doc, 1, "old content no keyword match here")
    latest_dv = await _seed_version(db_session, doc, 2, "sync lifecycle latest content here")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=1000,
    )
    matched = [s for s in result.sources if s.path == "versioned_ctx_doc.py"]
    assert len(matched) == 1
    assert matched[0].version_id == latest_dv.id


async def test_context_includes_all_fields(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "all_fields_ctx.py", is_active=True)
    dv = await _seed_version(db_session, doc, 1, "sync lifecycle content here for fields test")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=1000,
    )
    assert len(result.sources) == 1
    source = result.sources[0]
    assert source.path == "all_fields_ctx.py"
    assert source.document_id == doc.id
    assert source.version_id == dv.id
    assert 0.0 < source.score <= 1.0
    assert isinstance(source.excerpt, str)
    assert len(source.excerpt) > 0
    assert isinstance(source.excerpt_start, int)
    assert isinstance(source.excerpt_end, int)


async def test_context_returns_empty_sources_when_no_match(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "nomatch_ctx.py", is_active=True)
    await _seed_version(db_session, doc, 1, "hello world unrelated content here")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="zzzyyyxxx_nomatch_context",
        limit=5,
        max_chars=5000,
        excerpt_chars=1000,
    )
    assert result.sources == []
    assert result.used_chars == 0


async def test_context_used_chars_matches_sum_of_excerpts(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    for i in range(3):
        doc = await _seed_file_doc(
            db_session, repo, f"sum_check_ctx_{i}.py", is_active=True
        )
        await _seed_version(db_session, doc, 1, f"sync lifecycle component {i} " * 20)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=500,
    )
    assert result.used_chars == sum(len(s.excerpt) for s in result.sources)


async def test_context_offset_invariant_in_service_output(db_session: AsyncSession) -> None:
    repo = await _seed_conn_and_repo(db_session)
    content = (
        "prefix content here " * 20
        + "sync lifecycle management " * 10
        + " suffix text " * 20
    )
    doc = await _seed_file_doc(db_session, repo, "offset_check_ctx.py", is_active=True)
    await _seed_version(db_session, doc, 1, content)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.build_repository_context(
        repository_id=repo.id,
        query="sync lifecycle",
        limit=5,
        max_chars=5000,
        excerpt_chars=500,
    )
    assert len(result.sources) >= 1
    source = next(s for s in result.sources if s.path == "offset_check_ctx.py")
    assert content[source.excerpt_start:source.excerpt_end] == source.excerpt
```

- [ ] **Step 2: Run integration tests — verify FAIL**

```bash
pytest tests/integration/test_repository_context.py -v
```

Expected: `AttributeError: 'RetrievalService' object has no attribute 'build_repository_context'`

- [ ] **Step 3: Add `build_repository_context()` to `RetrievalService` in `lore/retrieval/service.py`**

Append this method inside `RetrievalService`, after `search_repository()`:

```python
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
        sources: list[ContextSourceItem] = []

        for item in ranked:
            remaining = max_chars - used
            if remaining < MIN_REMAINING_EXCERPT_CHARS:
                break
            per_source = min(excerpt_chars, remaining)
            excerpt = extract_context_excerpt(item.version.content, terms, per_source)
            if not excerpt.text:
                continue
            sources.append(
                ContextSourceItem(
                    path=item.document.path,
                    document_id=item.document.id,
                    version_id=item.version.id,
                    score=item.score,
                    excerpt=excerpt.text,
                    excerpt_start=excerpt.start,
                    excerpt_end=excerpt.end,
                )
            )
            used += len(excerpt.text)

        return RepositoryContextPackage(
            query=query, max_chars=max_chars, used_chars=used, sources=sources
        )
```

- [ ] **Step 4: Run integration tests — verify PASS**

```bash
pytest tests/integration/test_repository_context.py -v
```

Expected: 9 PASSED. If `test_context_includes_all_fields` fails because another doc from a prior test is in the same repo, check that path names are unique across tests (they are: each test uses unique suffix via `_seed_conn_and_repo`).

- [ ] **Step 5: Also run existing search tests to confirm no regression**

```bash
pytest tests/unit/retrieval/ tests/integration/test_repository_search.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add lore/retrieval/service.py tests/integration/test_repository_context.py
git commit -m "feat: add RetrievalService.build_repository_context with budget assembly"
```

---

## Task 4: Router Schemas + Endpoint + E2E Tests — TDD

**Files:**
- Create: `tests/e2e/test_repository_context_api.py`
- Modify: `apps/api/routes/v1/repositories.py`

- [ ] **Step 1: Write failing E2E tests**

Create `tests/e2e/test_repository_context_api.py`:

```python
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.source import SourceORM

pytestmark = pytest.mark.e2e


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_repo(session: AsyncSession) -> ExternalRepositoryORM:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:8]
    conn = ExternalConnectionORM(
        id=uuid4(),
        provider="github",
        auth_mode="env_pat",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(conn)
    await session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(),
        connection_id=conn.id,
        provider="github",
        owner=f"ctxe2eorg-{suffix}",
        name=f"ctxe2erepo-{suffix}",
        full_name=f"ctxe2eorg-{suffix}/ctxe2erepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/ctxe2eorg-{suffix}/ctxe2erepo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(repo)
    await session.flush()
    return repo


async def _seed_active_doc_with_version(
    session: AsyncSession,
    repo: ExternalRepositoryORM,
    path: str,
    content: str,
) -> tuple[DocumentORM, DocumentVersionORM]:
    now = datetime.now(UTC)
    eo = ExternalObjectORM(
        id=uuid4(),
        repository_id=repo.id,
        connection_id=repo.connection_id,
        provider="github",
        object_type="github.file",
        external_id=f"{repo.full_name}:file:{path}:{uuid4().hex[:6]}",
        raw_payload_json={},
        raw_payload_hash="hash-" + uuid4().hex[:8],
        fetched_at=now,
        metadata_={},
    )
    session.add(eo)
    await session.flush()

    src = SourceORM(
        id=uuid4(),
        source_type_raw="github.file",
        source_type_canonical="github.file",
        origin=f"https://github.com/{repo.full_name}/blob/main/{path}",
        external_object_id=eo.id,
        created_at=now,
        updated_at=now,
    )
    session.add(src)
    await session.flush()

    doc = DocumentORM(
        id=uuid4(),
        source_id=src.id,
        title=path,
        path=path,
        is_active=True,
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(doc)
    await session.flush()

    dv = DocumentVersionORM(
        id=uuid4(),
        document_id=doc.id,
        version=1,
        content=content,
        checksum=hashlib.sha256(content.encode()).hexdigest(),
        created_at=now,
        metadata_={},
    )
    session.add(dv)
    await session.flush()
    return doc, dv


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_context_happy_path(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    doc, dv = await _seed_active_doc_with_version(
        db_session,
        repo,
        "lore/sync/service.py",
        "this module handles sync lifecycle management in the system",
    )

    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/context",
        json={"query": "sync lifecycle", "limit": 5, "max_chars": 5000, "excerpt_chars": 1200},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["query"] == "sync lifecycle"
    assert data["max_chars"] == 5000
    assert isinstance(data["used_chars"], int)
    assert data["used_chars"] >= 0
    assert len(data["sources"]) >= 1

    first = data["sources"][0]
    assert first["path"] == "lore/sync/service.py"
    assert first["document_id"] == str(doc.id)
    assert first["version_id"] == str(dv.id)
    assert isinstance(first["score"], float)
    assert 0.0 < first["score"] <= 1.0
    assert isinstance(first["excerpt"], str)
    assert len(first["excerpt"]) > 0
    assert isinstance(first["excerpt_start"], int)
    assert isinstance(first["excerpt_end"], int)


async def test_context_returns_404_for_unknown_repository(
    app_client_with_db: httpx.AsyncClient,
) -> None:
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{uuid4()}/context",
        json={"query": "anything"},
    )
    assert response.status_code == 404


async def test_context_returns_422_for_empty_query(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/context",
        json={"query": ""},
    )
    assert response.status_code == 422


async def test_context_returns_422_for_whitespace_query(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/context",
        json={"query": "   "},
    )
    assert response.status_code == 422


async def test_context_returns_422_for_max_chars_out_of_range(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/context",
        json={"query": "sync", "max_chars": 500},  # below ge=1000
    )
    assert response.status_code == 422


async def test_context_returns_422_for_excerpt_chars_out_of_range(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/context",
        json={"query": "sync", "excerpt_chars": 100},  # below ge=300
    )
    assert response.status_code == 422


async def test_context_returns_422_when_excerpt_chars_exceeds_max_chars(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    # Both values are within their field ranges but excerpt_chars > max_chars
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/context",
        json={"query": "sync", "max_chars": 1000, "excerpt_chars": 1200},
    )
    assert response.status_code == 422


async def test_context_returns_200_with_empty_sources_when_no_match(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/context",
        json={"query": "zzzyyyxxx_nomatch_context_e2e"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sources"] == []
    assert data["used_chars"] == 0
```

- [ ] **Step 2: Run E2E tests — verify FAIL**

```bash
pytest tests/e2e/test_repository_context_api.py -v
```

Expected: route-related tests fail with 404/405 before the endpoint is registered. Validation tests (422 cases) will only start returning 422 after the endpoint and Pydantic schemas are wired up — before that they'll also return 404/405.

- [ ] **Step 3: Update imports in `apps/api/routes/v1/repositories.py`**

Change the existing `typing` import line from:
```python
from typing import TYPE_CHECKING, Annotated
```
to:
```python
from typing import TYPE_CHECKING, Annotated, Self
```

Change the existing `pydantic` import line from:
```python
from pydantic import BaseModel, Field, field_validator
```
to:
```python
from pydantic import BaseModel, Field, field_validator, model_validator
```

- [ ] **Step 4: Add new Pydantic schemas to `apps/api/routes/v1/repositories.py`**

After the `RepositorySearchResponse` class (around line 106), insert:

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

`RepositoryContextSource` here is a Pydantic response model — distinct from `ContextSourceItem` in `lore/retrieval/service.py`. Do **not** import `ContextSourceItem` by name; access service output via attributes (`s.path`, `s.excerpt`, etc.).

- [ ] **Step 5: Add the endpoint to `apps/api/routes/v1/repositories.py`**

After the `search_repository` endpoint handler (end of file), append:

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

- [ ] **Step 6: Run E2E tests — verify PASS**

```bash
pytest tests/e2e/test_repository_context_api.py -v
```

Expected: 8 PASSED.

- [ ] **Step 7: Commit**

```bash
git add apps/api/routes/v1/repositories.py tests/e2e/test_repository_context_api.py
git commit -m "feat: add POST /repositories/{id}/context endpoint"
```

---

## Task 5: Full Quality Gates

- [ ] **Step 1: Run all unit tests**

```bash
pytest -m unit -v
```

Expected: all pass, including new `test_context_excerpt.py`.

- [ ] **Step 2: Run all integration tests**

```bash
pytest -m integration -v
```

Expected: all pass, including new `test_repository_context.py`. Docker must be running (testcontainers spins up `pgvector/pgvector:pg16`).

- [ ] **Step 3: Run all E2E tests**

```bash
pytest -m e2e -v
```

Expected: all pass, including new `test_repository_context_api.py`.

- [ ] **Step 4: Run lint**

```bash
make lint
```

Expected: no issues. If ruff reports `TC003`/`TCH003` on `UUID` in service.py, the existing `# noqa: TC003, TCH003` comment on the `UUID` import covers it.

- [ ] **Step 5: Run type check**

```bash
make type-check
```

Expected: no errors. Known patterns:
- `_ScoredDocumentVersion` fields use `Document` and `DocumentVersion` from `TYPE_CHECKING` — fine under `from __future__ import annotations`.
- `Self` from `typing` requires Python ≥ 3.11; project requires 3.12. ✓

- [ ] **Step 6: Final commit if any lint/type fixes were needed**

```bash
git add -u
git commit -m "fix: address lint and type-check feedback for PR #10"
```

Only create this commit if step 4 or 5 required changes.
