from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Dataset models (Pydantic v2)
# ---------------------------------------------------------------------------


class RepositoryInfo(BaseModel):
    provider: str = Field(min_length=1)
    full_name: str = Field(min_length=1)


class RepositoryEvalCase(BaseModel):
    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected_paths: list[str] = Field(min_length=1)
    required_terms_any: list[str] = Field(default_factory=list)

    @field_validator("expected_paths", "required_terms_any")
    @classmethod
    def validate_non_blank_items(cls, values: list[str]) -> list[str]:
        # Blank paths are meaningless; blank terms always match any excerpt.
        if any(not value.strip() for value in values):
            raise ValueError("list items must be non-blank strings")
        return values


class RepositoryEvalDataset(BaseModel):
    name: str = Field(min_length=1)
    repository: RepositoryInfo
    cases: list[RepositoryEvalCase] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Runtime dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextSource:
    path: str
    excerpt: str | None = None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    query: str
    expected_paths: list[str]
    required_terms_any: list[str]
    search_paths: list[str]
    context_sources: list[ContextSource]
    search_top1_path_hit: bool
    search_top3_path_hit: bool
    search_top5_path_hit: bool
    context_path_hit: bool
    context_required_terms_hit: bool
    context_required_terms_applicable: bool


@dataclass(frozen=True)
class EvalSummary:
    total_cases: int
    search_top1_hits: int
    search_top3_hits: int
    search_top5_hits: int
    context_path_hits: int
    context_required_terms_hits: int
    context_required_terms_applicable: int


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_dataset(path: str | Path) -> RepositoryEvalDataset:
    # Raises ValueError for IO/JSON errors.
    # Raises pydantic.ValidationError for schema errors — callers handle both.
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read dataset file {path!r}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Dataset file {path!r} is not valid JSON: {exc}") from exc
    return RepositoryEvalDataset.model_validate(data)


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------


def normalize_path(path: str) -> str:
    return path.strip().lstrip("/")


# ---------------------------------------------------------------------------
# Response parsing — fail-fast on schema mismatch
# ---------------------------------------------------------------------------


def extract_search_paths(response: dict[str, Any]) -> list[str]:
    results = response.get("results")
    if not isinstance(results, list):
        raise ValueError("Search response must contain a 'results' list")
    paths: list[str] = []
    for index, item in enumerate(results):
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Search result at index {index} must contain non-empty 'path'")
        paths.append(normalize_path(path))
    return paths


def extract_context_sources(response: dict[str, Any]) -> list[ContextSource]:
    sources = response.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Context response must contain a 'sources' list")
    result: list[ContextSource] = []
    for index, item in enumerate(sources):
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Context source at index {index} must contain non-empty 'path'")
        excerpt = item.get("excerpt")
        if excerpt is not None and not isinstance(excerpt, str):
            raise ValueError(f"Context source at index {index}: 'excerpt' must be str or null")
        result.append(ContextSource(path=normalize_path(path), excerpt=excerpt))
    return result


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def has_expected_path_in_top_k(result_paths: list[str], expected_paths: list[str], k: int) -> bool:
    top_k = {normalize_path(p) for p in result_paths[:k]}
    expected = {normalize_path(p) for p in expected_paths}
    return bool(expected & top_k)


def has_context_path_hit(sources: list[ContextSource], expected_paths: list[str]) -> bool:
    paths = {normalize_path(s.path) for s in sources}
    expected = {normalize_path(p) for p in expected_paths}
    return bool(expected & paths)


def has_required_terms_hit(sources: list[ContextSource], required_terms_any: list[str]) -> bool:
    # Empty terms → not applicable → treated as passed.
    # Callers check is_required_terms_applicable to exclude from aggregate denominator.
    if not required_terms_any:
        return True
    terms_lower = [t.lower() for t in required_terms_any]
    for source in sources:
        if source.excerpt:
            excerpt_lower = source.excerpt.lower()
            if any(term in excerpt_lower for term in terms_lower):
                return True
    return False


def is_required_terms_applicable(required_terms_any: list[str]) -> bool:
    return bool(required_terms_any)
