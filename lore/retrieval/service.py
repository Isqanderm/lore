from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003, TCH003

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
