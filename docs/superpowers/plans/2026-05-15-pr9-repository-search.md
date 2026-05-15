# PR #9 — Repository Active Document Search v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/v1/repositories/{repository_id}/search` that lexically scores active documents with their latest version content and returns ranked results.

**Architecture:** Router checks repository existence via `ExternalRepositoryRepository`, delegates to `RetrievalService` which fetches active docs + latest versions via `DocumentRepository`, scores with pure Python functions, and returns domain dataclasses the router maps to HTTP response.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, pytest with testcontainers (pgvector/pgvector:pg16), Python 3.12 dataclasses.

---

## File Map

| Status | Path | Purpose |
|---|---|---|
| Create | `tests/unit/retrieval/__init__.py` | Package marker |
| Create | `tests/unit/retrieval/test_search_scorer.py` | Unit tests: tokenize, score, snippet |
| Create | `tests/integration/test_repository_search.py` | Integration tests: repo method + service |
| Create | `tests/e2e/test_repository_search_api.py` | E2E tests: HTTP contract |
| Modify | `lore/retrieval/service.py` | Domain types + pure functions + RetrievalService |
| Modify | `lore/infrastructure/db/repositories/document.py` | New repo method |
| Modify | `apps/api/routes/v1/repositories.py` | Pydantic schemas + endpoint handler |

---

## Task 1: Pure retrieval functions and domain types

**Files:**
- Create: `tests/unit/retrieval/__init__.py`
- Create: `tests/unit/retrieval/test_search_scorer.py`
- Modify: `lore/retrieval/service.py`

- [ ] **Step 1: Create the unit test package marker**

```bash
touch tests/unit/retrieval/__init__.py
```

- [ ] **Step 2: Write all unit tests (they will fail with ImportError first)**

Create `tests/unit/retrieval/test_search_scorer.py`:

```python
from __future__ import annotations

import pytest

from lore.retrieval.service import extract_snippet, score_document, tokenize_query

pytestmark = pytest.mark.unit


def test_tokenize_query_splits_on_non_word_chars() -> None:
    assert tokenize_query("github sync") == ["github", "sync"]


def test_tokenize_query_drops_single_char_tokens() -> None:
    assert tokenize_query("a b go") == ["go"]


def test_tokenize_query_returns_empty_list_for_blank() -> None:
    assert tokenize_query("") == []


def test_score_document_returns_zero_when_no_match() -> None:
    score = score_document("sync", ["sync"], "README.md", "hello world")
    assert score == 0.0


def test_score_document_term_in_path_gives_positive_score() -> None:
    score = score_document("sync", ["sync"], "lore/sync/service.py", "unrelated")
    assert score > 0.0


def test_score_document_term_in_content_gives_positive_score() -> None:
    score = score_document("sync", ["sync"], "README.md", "this is about sync lifecycle")
    assert score > 0.0


def test_score_document_phrase_in_path_scores_higher_than_term_only() -> None:
    # Use hyphen so the phrase is a literal substring of the path.
    # Underscore is a word char — "sync_service" does NOT contain "sync service".
    phrase_score = score_document(
        "sync-service", ["sync", "service"], "lore/sync-service/main.py", ""
    )
    content_only_score = score_document(
        "sync-service", ["sync", "service"], "no_match.py", "sync and service here"
    )
    assert phrase_score > content_only_score


def test_score_document_phrase_in_content_scores_higher_than_separated_terms() -> None:
    phrase_score = score_document(
        "sync lifecycle", ["sync", "lifecycle"], "other.py", "sync lifecycle here"
    )
    separated_score = score_document(
        "sync lifecycle", ["sync", "lifecycle"], "other.py", "sync and lifecycle separately"
    )
    assert phrase_score > separated_score


def test_score_document_clamped_to_one() -> None:
    content = " ".join(["sync"] * 100)
    score = score_document("sync", ["sync"], "sync/sync/sync.py", content)
    assert score <= 1.0


def test_score_document_none_content_does_not_crash_and_scores_path() -> None:
    score = score_document("sync", ["sync"], "lore/sync/service.py", None)
    assert score > 0.0


def test_extract_snippet_centers_on_first_matched_term() -> None:
    content = "a" * 100 + "TARGET" + "b" * 200
    snippet = extract_snippet(content, ["target"])
    assert "TARGET" in snippet


def test_extract_snippet_adds_ellipsis_prefix_when_match_is_deep() -> None:
    content = "x" * 300 + "needle" + "x" * 300
    snippet = extract_snippet(content, ["needle"])
    assert snippet.startswith("...")


def test_extract_snippet_adds_ellipsis_suffix_when_content_continues() -> None:
    content = "needle" + "x" * 300
    snippet = extract_snippet(content, ["needle"])
    assert snippet.endswith("...")


def test_extract_snippet_returns_beginning_when_no_term_match() -> None:
    content = "Hello world " * 30
    snippet = extract_snippet(content, ["notfound"])
    assert snippet.startswith("Hello world")
    assert len(snippet) <= 244  # 240 chars + possible "..."


def test_extract_snippet_returns_empty_for_none_content() -> None:
    assert extract_snippet(None, ["term"]) == ""


def test_extract_snippet_returns_empty_for_empty_string() -> None:
    assert extract_snippet("", ["term"]) == ""
```

- [ ] **Step 3: Run tests to confirm they fail (ImportError)**

```bash
cd /path/to/lore && .venv/bin/pytest tests/unit/retrieval/ -v 2>&1 | head -20
```

Expected: `ImportError` — `cannot import name 'extract_snippet' from 'lore.retrieval.service'`

- [ ] **Step 4: Implement pure functions, domain types, and service skeleton**

Replace the entire contents of `lore/retrieval/service.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from lore.infrastructure.db.repositories.document import DocumentRepository


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


def tokenize_query(query: str) -> list[str]:
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
    if not content:
        return ""
    content_lower = content.lower()
    half = length // 2
    for term in terms:
        idx = content_lower.find(term)
        if idx != -1:
            start = max(0, idx - half)
            end = min(len(content), start + length)
            start = max(0, end - length)
            snippet = content[start:end]
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(content) else ""
            return prefix + snippet + suffix
    snippet = content[:length]
    suffix = "..." if len(content) > length else ""
    return snippet + suffix


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
        raise NotImplementedError
```

- [ ] **Step 5: Run unit tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/retrieval/ -v
```

Expected output: 16 tests PASSED.

- [ ] **Step 6: Run lint and type check**

```bash
make lint && make type-check
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add lore/retrieval/service.py tests/unit/retrieval/__init__.py tests/unit/retrieval/test_search_scorer.py
git commit -m "feat: add retrieval pure functions and domain types"
```

---

## Task 2: DocumentRepository — active documents with latest versions

**Files:**
- Create: `tests/integration/test_repository_search.py`
- Modify: `lore/infrastructure/db/repositories/document.py`

- [ ] **Step 1: Write integration test file with seed helpers and repository method tests**

> **Before using the seed helpers below:** compare them with the existing helpers in `tests/integration/test_document_active_state.py`. The code below is a template. If `DocumentORM` has acquired required fields (e.g., `document_kind`, `logical_path`) in newer migrations, include those fields. Prefer reusing existing helpers if they are importable; otherwise copy and extend.

Create `tests/integration/test_repository_search.py`:

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
        owner=f"searchorg-{suffix}",
        name=f"searchrepo-{suffix}",
        full_name=f"searchorg-{suffix}/searchrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/searchorg-{suffix}/searchrepo-{suffix}",
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


# ── DocumentRepository method tests ───────────────────────────────────────────


async def test_get_active_documents_with_latest_versions_returns_active_doc(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "README.md", is_active=True)
    dv = await _seed_version(db_session, doc, 1, "hello world")

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    paths = [d.path for d, _ in pairs]
    assert "README.md" in paths
    version_ids = [v.id for _, v in pairs]
    assert dv.id in version_ids


async def test_get_active_documents_with_latest_versions_excludes_inactive_doc(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "deleted.py", is_active=False)
    await _seed_version(db_session, doc, 1, "some content")

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    paths = [d.path for d, _ in pairs]
    assert "deleted.py" not in paths


async def test_get_active_documents_with_latest_versions_skips_doc_without_versions(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    await _seed_file_doc(db_session, repo, "no-version.md", is_active=True)

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    paths = [d.path for d, _ in pairs]
    assert "no-version.md" not in paths


async def test_get_active_documents_with_latest_versions_returns_only_latest_version(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "service.py", is_active=True)
    await _seed_version(db_session, doc, 1, "old content")
    latest_dv = await _seed_version(db_session, doc, 2, "new content")

    pairs = await DocumentRepository(
        db_session
    ).get_active_documents_with_latest_versions_by_repository_id(repo.id)

    matched = [(d, v) for d, v in pairs if d.path == "service.py"]
    assert len(matched) == 1
    _, version = matched[0]
    assert version.id == latest_dv.id
    assert version.content == "new content"
```

- [ ] **Step 2: Run to confirm failure (method doesn't exist yet)**

```bash
.venv/bin/pytest tests/integration/test_repository_search.py::test_get_active_documents_with_latest_versions_returns_active_doc -v
```

Expected: `AttributeError: 'DocumentRepository' object has no attribute 'get_active_documents_with_latest_versions_by_repository_id'`

- [ ] **Step 3: Implement the repository method in `lore/infrastructure/db/repositories/document.py`**

Add this method to the `DocumentRepository` class, after the existing `get_by_source_kind_path` method. The method mirrors the join pattern of the existing `get_active_document_paths_by_repository_id` — reuse the same JOINs and `_GITHUB_FILE_OBJECT_TYPE` constant.

```python
async def get_active_documents_with_latest_versions_by_repository_id(
    self, repository_id: UUID
) -> list[tuple[Document, DocumentVersion]]:
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

    result = await self.session.execute(stmt)
    rows = result.all()
    return [
        (_doc_orm_to_schema(doc_orm), _dv_orm_to_schema(dv_orm))
        for doc_orm, dv_orm in rows
    ]
```

Note: `func` is already imported at the module level in `document.py`. `select` is already imported. No new imports needed. The module already imports `DocumentVersionORM`, `SourceORM`, `ExternalObjectORM`, `_doc_orm_to_schema`, `_dv_orm_to_schema`, and `_GITHUB_FILE_OBJECT_TYPE`.

- [ ] **Step 4: Run the four repository method tests to confirm they pass**

```bash
.venv/bin/pytest tests/integration/test_repository_search.py -k "get_active_documents" -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Run lint and type check**

```bash
make lint && make type-check
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add lore/infrastructure/db/repositories/document.py tests/integration/test_repository_search.py
git commit -m "feat: add get_active_documents_with_latest_versions_by_repository_id"
```

---

## Task 3: RetrievalService.search_repository

**Files:**
- Modify: `tests/integration/test_repository_search.py` (add service tests)
- Modify: `lore/retrieval/service.py` (implement `search_repository`)

- [ ] **Step 1: Add service integration tests to `tests/integration/test_repository_search.py`**

Append these tests after the last existing test in the file:

```python
# ── RetrievalService integration tests ───────────────────────────────────────


async def test_search_repository_excludes_inactive_documents(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)

    active_doc = await _seed_file_doc(db_session, repo, "active.py", is_active=True)
    await _seed_version(db_session, active_doc, 1, "this file handles authentication logic")

    # Inactive doc with stronger content match — must NOT appear
    inactive_doc = await _seed_file_doc(
        db_session, repo, "authentication/service.py", is_active=False
    )
    await _seed_version(
        db_session, inactive_doc, 1, "authentication " * 10
    )

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=10)

    paths = [r.path for r in result.results]
    assert "active.py" in paths
    assert "authentication/service.py" not in paths


async def test_search_repository_skips_doc_when_only_old_version_matches(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "service_old_match.py", is_active=True)
    await _seed_version(db_session, doc, 1, "authentication logic here")
    await _seed_version(db_session, doc, 2, "unrelated content entirely")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=10)

    paths = [r.path for r in result.results]
    assert "service_old_match.py" not in paths


async def test_search_repository_uses_latest_document_version(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    doc = await _seed_file_doc(db_session, repo, "handler_latest.py", is_active=True)
    await _seed_version(db_session, doc, 1, "unrelated old content")
    latest_dv = await _seed_version(db_session, doc, 2, "sync lifecycle management")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "sync lifecycle", limit=10)

    matched = [r for r in result.results if r.path == "handler_latest.py"]
    assert len(matched) == 1
    assert matched[0].version_id == latest_dv.id


async def test_search_repository_scoped_to_target_repository(
    db_session: AsyncSession,
) -> None:
    repo_a = await _seed_conn_and_repo(db_session)
    repo_b = await _seed_conn_and_repo(db_session)

    doc_a = await _seed_file_doc(db_session, repo_a, "auth_topic.py", is_active=True)
    await _seed_version(db_session, doc_a, 1, "authentication service")

    doc_b = await _seed_file_doc(db_session, repo_b, "auth_topic.py", is_active=True)
    await _seed_version(db_session, doc_b, 1, "authentication service")

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo_a.id, "authentication", limit=10)

    doc_ids = [r.document_id for r in result.results]
    assert doc_a.id in doc_ids
    assert doc_b.id not in doc_ids


async def test_search_repository_respects_limit(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)
    for i in range(5):
        doc = await _seed_file_doc(
            db_session, repo, f"limit_test_{i}.py", is_active=True
        )
        await _seed_version(
            db_session, doc, 1, f"authentication service component {i} " * 5
        )

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=3)

    assert len(result.results) == 3


async def test_search_repository_ranks_stronger_match_first(
    db_session: AsyncSession,
) -> None:
    repo = await _seed_conn_and_repo(db_session)

    # Weak: term in content once
    weak_doc = await _seed_file_doc(db_session, repo, "rank_misc.py", is_active=True)
    await _seed_version(db_session, weak_doc, 1, "authentication mentioned once")

    # Strong: phrase in path + many content hits
    strong_doc = await _seed_file_doc(
        db_session, repo, "authentication/rank_service.py", is_active=True
    )
    await _seed_version(db_session, strong_doc, 1, "authentication " * 10)

    svc = RetrievalService(document_repository=DocumentRepository(db_session))
    result = await svc.search_repository(repo.id, "authentication", limit=10)

    assert len(result.results) >= 2
    assert result.results[0].path == "authentication/rank_service.py"
```

- [ ] **Step 2: Run tests to confirm they fail (NotImplementedError)**

```bash
.venv/bin/pytest tests/integration/test_repository_search.py -k "not get_active_documents" -v 2>&1 | head -30
```

Expected: all 6 service tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `search_repository` in `lore/retrieval/service.py`**

Replace the `raise NotImplementedError` stub in `RetrievalService.search_repository`:

```python
async def search_repository(
    self,
    repository_id: UUID,
    query: str,
    limit: int,
) -> RepositorySearchResultSet:
    pairs = await self._document_repository.get_active_documents_with_latest_versions_by_repository_id(
        repository_id
    )
    terms = tokenize_query(query)

    scored: list[tuple[float, str, object, object]] = []
    for doc, version in pairs:
        s = score_document(query, terms, doc.path, version.content)
        if s > 0:
            scored.append((s, doc.path, doc, version))

    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:limit]

    hits = [
        RetrievalHit(
            path=doc.path,
            document_id=doc.id,
            version_id=version.id,
            snippet=extract_snippet(version.content, terms),
            score=score,
        )
        for score, _, doc, version in top
    ]

    return RepositorySearchResultSet(query=query, results=hits)
```

The full `search_repository` method with proper types — replace the whole method in the class:

```python
async def search_repository(
    self,
    repository_id: UUID,
    query: str,
    limit: int,
) -> RepositorySearchResultSet:
    from lore.schema.document import Document, DocumentVersion

    pairs: list[tuple[Document, DocumentVersion]] = (
        await self._document_repository
        .get_active_documents_with_latest_versions_by_repository_id(repository_id)
    )
    terms = tokenize_query(query)

    scored: list[tuple[float, str, Document, DocumentVersion]] = []
    for doc, version in pairs:
        s = score_document(query, terms, doc.path, version.content)
        if s > 0:
            scored.append((s, doc.path, doc, version))

    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:limit]

    hits = [
        RetrievalHit(
            path=doc.path,
            document_id=doc.id,
            version_id=version.id,
            snippet=extract_snippet(version.content, terms),
            score=s,
        )
        for s, _, doc, version in top
    ]

    return RepositorySearchResultSet(query=query, results=hits)
```

- [ ] **Step 4: Run all integration tests in the file to confirm they pass**

```bash
.venv/bin/pytest tests/integration/test_repository_search.py -v
```

Expected: 10 tests PASSED (4 repo method tests + 6 service tests).

- [ ] **Step 5: Run lint and type check**

```bash
make lint && make type-check
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add lore/retrieval/service.py tests/integration/test_repository_search.py
git commit -m "feat: implement RetrievalService.search_repository"
```

---

## Task 4: Router endpoint and E2E tests

**Files:**
- Create: `tests/e2e/test_repository_search_api.py`
- Modify: `apps/api/routes/v1/repositories.py`

- [ ] **Step 1: Write E2E tests (they will fail with 404 — route not found yet)**

Create `tests/e2e/test_repository_search_api.py`:

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
        owner=f"e2eorg-{suffix}",
        name=f"e2erepo-{suffix}",
        full_name=f"e2eorg-{suffix}/e2erepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/e2eorg-{suffix}/e2erepo-{suffix}",
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


async def test_search_repository_returns_422_for_empty_query(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": ""},
    )
    assert response.status_code == 422


async def test_search_repository_returns_422_for_whitespace_query(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": "   "},
    )
    assert response.status_code == 422


async def test_search_repository_returns_200_with_empty_results_when_no_match(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": "zzzyyyxxx_nomatch_e2e"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "zzzyyyxxx_nomatch_e2e"
    assert data["results"] == []


async def test_search_repository_returns_404_for_unknown_repository(
    app_client_with_db: httpx.AsyncClient,
) -> None:
    unknown_id = uuid4()
    response = await app_client_with_db.post(
        f"/api/v1/repositories/{unknown_id}/search",
        json={"query": "anything"},
    )
    assert response.status_code == 404


async def test_search_repository_happy_path(
    app_client_with_db: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    repo = await _seed_repo(db_session)
    doc, dv = await _seed_active_doc_with_version(
        db_session,
        repo,
        "lore/sync/service.py",
        "this module handles sync lifecycle management",
    )

    response = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/search",
        json={"query": "sync lifecycle"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["query"] == "sync lifecycle"
    assert len(data["results"]) >= 1

    first = data["results"][0]
    assert first["path"] == "lore/sync/service.py"
    assert first["document_id"] == str(doc.id)
    assert first["version_id"] == str(dv.id)
    assert isinstance(first["snippet"], str)
    assert len(first["snippet"]) > 0
    assert isinstance(first["score"], float)
    assert 0.0 < first["score"] <= 1.0
```

- [ ] **Step 2: Run to confirm tests fail (route not found)**

```bash
.venv/bin/pytest tests/e2e/test_repository_search_api.py -v 2>&1 | head -30
```

Expected: tests fail with 404 or 405 (route not registered yet).

- [ ] **Step 3: Add Pydantic schemas and endpoint to `apps/api/routes/v1/repositories.py`**

**3a. Update the pydantic import line** — add `field_validator`:

Find the existing line:
```python
from pydantic import BaseModel, Field
```
Replace with:
```python
from pydantic import BaseModel, Field, field_validator
```

**3b. Add import for `RetrievalService`** — insert after the existing `lore.sync` imports:

```python
from lore.retrieval.service import RetrievalService
```

**3c. Add schemas** — insert before the `_build_import_service` function (after the existing `RepositorySyncRunListItem` class):

```python
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

**3d. Add the endpoint handler** — append at the end of the file, after the `list_sync_runs` function:

```python
@router.post("/{repository_id}/search", response_model=RepositorySearchResponse)
async def search_repository(
    repository_id: UUID,
    body: RepositorySearchRequest,
    session: SessionDep,
) -> RepositorySearchResponse:
    repo_repo = ExternalRepositoryRepository(session)
    repo = await repo_repo.get_by_id(repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    doc_repo = DocumentRepository(session)
    svc = RetrievalService(document_repository=doc_repo)
    result = await svc.search_repository(repository_id, body.query, body.limit)

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

Note: `ExternalRepositoryRepository`, `DocumentRepository`, `HTTPException`, `UUID`, and `SessionDep` are already imported in this file. No additional imports needed beyond `field_validator` and `RetrievalService`.

- [ ] **Step 4: Run E2E tests to confirm they pass**

```bash
.venv/bin/pytest tests/e2e/test_repository_search_api.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Run full test suite**

```bash
make test
```

Expected: all unit, integration, and e2e tests pass.

- [ ] **Step 6: Run lint and type check**

```bash
make lint && make type-check
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add apps/api/routes/v1/repositories.py tests/e2e/test_repository_search_api.py
git commit -m "feat: add POST /repositories/{id}/search endpoint"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|---|---|
| `POST /repositories/{id}/search` endpoint | Task 4 |
| Request: `query` (1–500, non-blank) + `limit` (1–50, default 10) | Task 4 |
| Response: `query` + `results[]` with all 5 fields | Task 4 |
| Only `is_active=True` documents | Task 2 (repo method) + integration test A |
| Only latest `DocumentVersion` | Task 2 (repo method) + integration tests B1/B2 |
| Docs without versions silently skipped | Task 2 integration test |
| Repository scope via `ExternalObjectORM.repository_id` join | Task 2 |
| Score sorted DESC, path ASC tie-break | Task 3 (service impl) + integration test E |
| Limit applied after sorting | Task 3 (service impl) + integration test D |
| Empty/whitespace query → 422 | Task 4 E2E tests |
| Unknown repository → 404 | Task 4 E2E test |
| No matches → 200 `{ results: [] }` | Task 4 E2E test |
| `score_document` + `tokenize_query` + `extract_snippet` pure functions | Task 1 |
| Domain dataclasses `RetrievalHit` + `RepositorySearchResultSet` | Task 1 |
| No Pydantic schemas in service layer | Task 1/3 |
| Repository existence check in router only | Task 4 |

All requirements covered.

### Type consistency

- `tokenize_query(query: str) -> list[str]` — used correctly in `search_repository`
- `score_document(query, terms, path, content: str | None) -> float` — `version.content` is `str` (confirmed in `lore/schema/document.py:29`), passes fine to `str | None`
- `extract_snippet(content: str | None, terms, length) -> str` — same
- `RetrievalHit.document_id: UUID` matches `Document.id: UUID`
- `RetrievalHit.version_id: UUID` matches `DocumentVersion.id: UUID`
- `RepositorySearchResultSet.results: list[RetrievalHit]` — constructed with list literal, no default factory issue
- Router maps `hit.document_id` → `RepositorySearchResult.document_id: UUID` — consistent

### No placeholders

Checked: no TBD, no "add appropriate error handling", no "similar to task N" without code.
