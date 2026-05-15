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


# ---------------------------------------------------------------------------
# Ratio helpers
# ---------------------------------------------------------------------------


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def search_top3_ratio(summary: EvalSummary) -> float:
    return ratio(summary.search_top3_hits, summary.total_cases)


def context_path_ratio(summary: EvalSummary) -> float:
    return ratio(summary.context_path_hits, summary.total_cases)


def context_terms_ratio(summary: EvalSummary) -> float | None:
    if summary.context_required_terms_applicable == 0:
        return None
    return ratio(summary.context_required_terms_hits, summary.context_required_terms_applicable)


# ---------------------------------------------------------------------------
# Case evaluation and aggregation
# ---------------------------------------------------------------------------


def evaluate_case(
    case: RepositoryEvalCase,
    search_paths: list[str],
    context_sources: list[ContextSource],
) -> CaseResult:
    applicable = is_required_terms_applicable(case.required_terms_any)
    return CaseResult(
        case_id=case.id,
        query=case.query,
        expected_paths=case.expected_paths,
        required_terms_any=case.required_terms_any,
        search_paths=search_paths,
        context_sources=context_sources,
        search_top1_path_hit=has_expected_path_in_top_k(search_paths, case.expected_paths, 1),
        search_top3_path_hit=has_expected_path_in_top_k(search_paths, case.expected_paths, 3),
        search_top5_path_hit=has_expected_path_in_top_k(search_paths, case.expected_paths, 5),
        context_path_hit=has_context_path_hit(context_sources, case.expected_paths),
        context_required_terms_hit=has_required_terms_hit(context_sources, case.required_terms_any),
        context_required_terms_applicable=applicable,
    )


def summarize_results(results: list[CaseResult]) -> EvalSummary:
    return EvalSummary(
        total_cases=len(results),
        search_top1_hits=sum(1 for r in results if r.search_top1_path_hit),
        search_top3_hits=sum(1 for r in results if r.search_top3_path_hit),
        search_top5_hits=sum(1 for r in results if r.search_top5_path_hit),
        context_path_hits=sum(1 for r in results if r.context_path_hit),
        context_required_terms_hits=sum(
            1
            for r in results
            if r.context_required_terms_applicable and r.context_required_terms_hit
        ),
        context_required_terms_applicable=sum(
            1 for r in results if r.context_required_terms_applicable
        ),
    )


def thresholds_passed(summary: EvalSummary, min_top3: float, min_context_hit: float) -> bool:
    # context_required_terms_hit is diagnostic in v1 — not a gate.
    return search_top3_ratio(summary) >= min_top3 and context_path_ratio(summary) >= min_context_hit


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _is_case_failed(result: CaseResult) -> bool:
    # A case appears in Failures if any primary check failed.
    # context_required_terms_hit is shown in failures even though it is not a
    # threshold gate in v1 — it is useful diagnostic information.
    if not result.search_top3_path_hit:
        return True
    if not result.context_path_hit:
        return True
    if result.context_required_terms_applicable and not result.context_required_terms_hit:
        return True
    return False


def _format_pct(numerator: int, denominator: int) -> str:
    pct = ratio(numerator, denominator) * 100
    return f"{numerator}/{denominator}  {pct:.1f}%"


def format_report(
    dataset: RepositoryEvalDataset,
    results: list[CaseResult],
    summary: EvalSummary,
    min_top3: float,
    min_context_hit: float,
) -> str:
    lines: list[str] = []
    w = 22

    lines.append(f"Repository Retrieval Eval: {dataset.name}")
    lines.append("")
    lines.append("Repository:")
    lines.append(f"  provider: {dataset.repository.provider}")
    lines.append(f"  full_name: {dataset.repository.full_name}")
    lines.append("")
    lines.append(f"Cases: {summary.total_cases}")
    lines.append("")

    lines.append(
        f"{'search_top1_path_hit:':<{w}} "
        f"{_format_pct(summary.search_top1_hits, summary.total_cases)}"
    )
    lines.append(
        f"{'search_top3_path_hit:':<{w}} "
        f"{_format_pct(summary.search_top3_hits, summary.total_cases)}"
    )
    lines.append(
        f"{'search_top5_path_hit:':<{w}} "
        f"{_format_pct(summary.search_top5_hits, summary.total_cases)}"
    )
    lines.append(
        f"{'context_path_hit:':<{w}} "
        f"{_format_pct(summary.context_path_hits, summary.total_cases)}"
    )

    terms_r = context_terms_ratio(summary)
    if terms_r is None:
        lines.append(f"{'context_terms_hit:':<{w}} n/a")
    else:
        app = summary.context_required_terms_applicable
        lines.append(
            f"{'context_terms_hit:':<{w}} "
            f"{summary.context_required_terms_hits}/{app} applicable  {terms_r * 100:.1f}%"
        )

    lines.append("")
    lines.append("Thresholds:")
    lines.append(f"  min_top3:        {min_top3 * 100:.1f}%")
    lines.append(f"  min_context_hit: {min_context_hit * 100:.1f}%")
    lines.append("")
    lines.append(
        f"Result: {'PASS' if thresholds_passed(summary, min_top3, min_context_hit) else 'FAIL'}"
    )

    failures = [r for r in results if _is_case_failed(r)]
    if failures:
        lines.append("")
        lines.append("Failures:")
        for result in failures:
            failed_checks: list[str] = []
            if not result.search_top1_path_hit:
                failed_checks.append("search_top1_path_hit")
            if not result.search_top3_path_hit:
                failed_checks.append("search_top3_path_hit")
            if not result.search_top5_path_hit:
                failed_checks.append("search_top5_path_hit")
            if not result.context_path_hit:
                failed_checks.append("context_path_hit")
            if result.context_required_terms_applicable and not result.context_required_terms_hit:
                failed_checks.append("context_terms_hit")

            lines.append(f"- {result.case_id}")
            lines.append(f"  query: {result.query}")
            lines.append("  expected_paths:")
            for p in result.expected_paths:
                lines.append(f"    - {p}")
            lines.append("  search_top5:")
            for p in result.search_paths[:5]:
                lines.append(f"    - {p}")
            lines.append("  context_paths:")
            for src in result.context_sources:
                lines.append(f"    - {src.path}")
            if result.required_terms_any:
                lines.append("  required_terms_any:")
                for t in result.required_terms_any:
                    lines.append(f"    - {t}")
                lines.append(
                    f"  context_terms_hit: "
                    f"{'true' if result.context_required_terms_hit else 'false'}"
                )
            lines.append(f"  failed_checks: [{', '.join(failed_checks)}]")

    return "\n".join(lines)
