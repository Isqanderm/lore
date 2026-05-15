from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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
