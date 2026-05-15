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


def tokenize_query(query: str) -> list[str]:
    return [token.lower() for token in re.split(r"\W+", query) if len(token) >= 2]


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
        pairs: list[
            tuple[Document, DocumentVersion]
        ] = await self._document_repository.get_active_documents_with_latest_versions_by_repository_id(
            repository_id
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
