from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003, TCH003

if TYPE_CHECKING:
    from lore.infrastructure.db.repositories.document import DocumentRepository
    from lore.schema.document import Document, DocumentVersion


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


MIN_REMAINING_EXCERPT_CHARS = 300
MAX_TERM_OCCURRENCES_PER_TERM = 50


@dataclass(frozen=True)
class ContextExcerpt:
    """Excerpt with character offsets into original content.

    Invariant: content[start:end] == text
    """

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _TermOccurrence:
    term: str
    index: int


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


RETRIEVAL_EXCLUDED_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        ".parcel-cache",
        ".svelte-kit",
        "node_modules",
        "bower_components",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        "target",
    }
)

RETRIEVAL_EXCLUDED_FILENAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "pipfile.lock",
        "cargo.lock",
        "composer.lock",
        "gemfile.lock",
    }
)

RETRIEVAL_EXCLUDED_SUFFIXES: tuple[str, ...] = (
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".wasm",
    ".br",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
)


def _is_retrievable_repository_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().lower()
    if not normalized:
        return False
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return False
    if any(segment in RETRIEVAL_EXCLUDED_PATH_SEGMENTS for segment in segments):
        return False
    filename = segments[-1]
    if filename in RETRIEVAL_EXCLUDED_FILENAMES:
        return False
    return not filename.endswith(RETRIEVAL_EXCLUDED_SUFFIXES)


QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "where",
        "which",
        "with",
        "within",
    }
)


def tokenize_query(query: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in re.split(r"\W+", query):
        token = raw_token.lower()
        if len(token) >= 2 and token not in QUERY_STOPWORDS:
            tokens.append(token)
    return tokens


PATH_TERM_WEIGHT: float = 4.0
BASENAME_TERM_WEIGHT: float = 6.0
CONTENT_TERM_WEIGHT: float = 1.0
PATH_PHRASE_WEIGHT: float = 15.0
CONTENT_PHRASE_WEIGHT: float = 8.0
MAX_CONTENT_TERM_MATCHES: int = 10
MAX_RAW_SCORE: float = 40.0


def score_document(
    query: str,
    terms: list[str],
    path: str,
    content: str | None,
) -> float:
    path_lower = path.lower()
    basename_lower = path_lower.rsplit("/", 1)[-1]
    content_lower = (content or "").lower()
    phrase = query.lower().strip()
    raw_score = 0.0
    for term in terms:
        if term in path_lower:
            raw_score += PATH_TERM_WEIGHT
        if term in basename_lower:
            raw_score += BASENAME_TERM_WEIGHT
        count = content_lower.count(term)
        raw_score += min(count, MAX_CONTENT_TERM_MATCHES) * CONTENT_TERM_WEIGHT
    if phrase and phrase in path_lower:
        raw_score += PATH_PHRASE_WEIGHT
    if phrase and phrase in content_lower:
        raw_score += CONTENT_PHRASE_WEIGHT
    return min(raw_score / MAX_RAW_SCORE, 1.0)


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


def _find_term_occurrences(content_lower: str, terms: list[str]) -> list[_TermOccurrence]:
    occurrences: list[_TermOccurrence] = []
    seen_terms: set[str] = set()

    for term in terms:
        term_lower = term.lower()
        if not term_lower or term_lower in seen_terms:
            continue
        seen_terms.add(term_lower)

        start = 0
        found_for_term = 0

        while found_for_term < MAX_TERM_OCCURRENCES_PER_TERM:
            index = content_lower.find(term_lower, start)
            if index == -1:
                break
            occurrences.append(_TermOccurrence(term=term_lower, index=index))
            found_for_term += 1
            start = index + 1

    return occurrences


def _score_window(
    occurrences: list[_TermOccurrence],
    start: int,
    end: int,
) -> tuple[int, int, int]:
    unique: set[str] = set()
    total = 0
    for occ in occurrences:
        if start <= occ.index < end:
            unique.add(occ.term)
            total += 1
    return (len(unique), total, -start)


def _find_best_excerpt_window(
    content_len: int,
    occurrences: list[_TermOccurrence],
    max_chars: int,
) -> tuple[int, int]:
    if not occurrences:
        return (0, min(content_len, max_chars))

    half = max_chars // 2
    best_score: tuple[int, int, int] | None = None
    best_window: tuple[int, int] = (0, min(content_len, max_chars))

    for occ in occurrences:
        start = max(0, occ.index - half)
        start = min(start, max(0, content_len - max_chars))
        end = min(content_len, start + max_chars)
        score = _score_window(occurrences, start, end)
        if best_score is None or score > best_score:
            best_score = score
            best_window = (start, end)

    return best_window


def extract_context_excerpt(
    content: str | None,
    terms: list[str],
    max_chars: int,
) -> ContextExcerpt:
    if max_chars <= 0 or not content:
        return ContextExcerpt(text="", start=0, end=0)

    content_lower = content.lower()
    occurrences = _find_term_occurrences(content_lower, terms)
    start, end = _find_best_excerpt_window(len(content), occurrences, max_chars)
    return ContextExcerpt(text=content[start:end], start=start, end=end)


@dataclass(frozen=True)
class _ScoredDocumentVersion:
    """Internal implementation detail — not part of the public retrieval API."""

    document: Document
    version: DocumentVersion
    score: float


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
            if not _is_retrievable_repository_path(doc.path):
                continue
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
