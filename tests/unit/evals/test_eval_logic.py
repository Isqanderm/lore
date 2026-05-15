from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from evals.repository_retrieval.eval_logic import (
    CaseResult,
    ContextSource,
    EvalSummary,
    RepositoryEvalCase,
    RepositoryEvalDataset,
    RepositoryInfo,
    context_path_ratio,
    context_terms_ratio,
    evaluate_case,
    extract_context_sources,
    extract_search_paths,
    format_report,
    has_context_path_hit,
    has_expected_path_in_top_k,
    has_required_terms_hit,
    load_dataset,
    normalize_path,
    ratio,
    search_top3_ratio,
    summarize_results,
    thresholds_passed,
)

pytestmark = pytest.mark.unit

_VALID_DATASET: dict[str, Any] = {
    "name": "test-eval",
    "repository": {"provider": "github", "full_name": "Isqanderm/lore"},
    "cases": [
        {
            "id": "case-1",
            "query": "How does sync work?",
            "expected_paths": ["lore/sync/service.py"],
            "required_terms_any": ["sync"],
        }
    ],
}


def test_load_dataset_valid(tmp_path: Path) -> None:
    f = Path(tmp_path) / "eval.json"
    f.write_text(json.dumps(_VALID_DATASET), encoding="utf-8")
    dataset = load_dataset(f)
    assert dataset.name == "test-eval"
    assert len(dataset.cases) == 1
    assert dataset.cases[0].id == "case-1"
    assert dataset.cases[0].expected_paths == ["lore/sync/service.py"]


def test_load_dataset_empty_cases() -> None:
    data: dict[str, Any] = {**_VALID_DATASET, "cases": []}
    with pytest.raises(ValidationError):
        RepositoryEvalDataset.model_validate(data)


def test_load_dataset_empty_id() -> None:
    cases: list[Any] = [{**_VALID_DATASET["cases"][0], "id": ""}]
    data: dict[str, Any] = {**_VALID_DATASET, "cases": cases}
    with pytest.raises(ValidationError):
        RepositoryEvalDataset.model_validate(data)


def test_load_dataset_empty_expected_paths() -> None:
    cases: list[Any] = [{**_VALID_DATASET["cases"][0], "expected_paths": []}]
    data: dict[str, Any] = {**_VALID_DATASET, "cases": cases}
    with pytest.raises(ValidationError):
        RepositoryEvalDataset.model_validate(data)


def test_load_dataset_blank_path_item_raises() -> None:
    # expected_paths: [""] must be rejected — blank string is not a valid path
    cases: list[Any] = [{**_VALID_DATASET["cases"][0], "expected_paths": [""]}]
    data: dict[str, Any] = {**_VALID_DATASET, "cases": cases}
    with pytest.raises(ValidationError):
        RepositoryEvalDataset.model_validate(data)


def test_load_dataset_blank_term_item_raises() -> None:
    # required_terms_any: [""] must be rejected — "" always matches any excerpt
    cases: list[Any] = [{**_VALID_DATASET["cases"][0], "required_terms_any": [""]}]
    data: dict[str, Any] = {**_VALID_DATASET, "cases": cases}
    with pytest.raises(ValidationError):
        RepositoryEvalDataset.model_validate(data)


def test_load_dataset_invalid_schema_raises_validation_error(tmp_path: Path) -> None:
    from pathlib import Path as PathlibPath

    # load_dataset raises ValidationError (not ValueError) for schema errors
    f = PathlibPath(tmp_path) / "eval.json"
    f.write_text(json.dumps({**_VALID_DATASET, "cases": []}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_dataset(f)


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------


def test_normalize_path_strips_leading_slash() -> None:
    assert normalize_path("/foo/bar.py") == "foo/bar.py"


def test_normalize_path_strips_whitespace() -> None:
    assert normalize_path("  foo/bar.py  ") == "foo/bar.py"


# ---------------------------------------------------------------------------
# extract_search_paths
# ---------------------------------------------------------------------------


def test_extract_search_paths_real_schema() -> None:
    response = {
        "query": "test",
        "results": [
            {
                "path": "foo/bar.py",
                "snippet": "some text",
                "score": 0.9,
                "document_id": "00000000-0000-0000-0000-000000000001",
                "version_id": "00000000-0000-0000-0000-000000000002",
            }
        ],
    }
    paths = extract_search_paths(response)
    assert paths == ["foo/bar.py"]


def test_extract_search_paths_missing_results() -> None:
    with pytest.raises(ValueError, match="'results' list"):
        extract_search_paths({})


def test_extract_search_paths_missing_path() -> None:
    response = {"results": [{"snippet": "...", "score": 0.9}]}
    with pytest.raises(ValueError, match="index 0"):
        extract_search_paths(response)


# ---------------------------------------------------------------------------
# extract_context_sources
# ---------------------------------------------------------------------------


def test_extract_context_sources_real_schema() -> None:
    response = {
        "query": "test",
        "max_chars": 12000,
        "used_chars": 100,
        "sources": [
            {
                "path": "foo/bar.py",
                "excerpt": "some text",
                "score": 0.9,
                "document_id": "00000000-0000-0000-0000-000000000001",
                "version_id": "00000000-0000-0000-0000-000000000002",
                "excerpt_start": 0,
                "excerpt_end": 9,
            }
        ],
    }
    sources = extract_context_sources(response)
    assert len(sources) == 1
    assert sources[0].path == "foo/bar.py"
    assert sources[0].excerpt == "some text"


def test_extract_context_sources_missing_sources() -> None:
    with pytest.raises(ValueError, match="'sources' list"):
        extract_context_sources({})


def test_extract_context_sources_invalid_excerpt_type() -> None:
    response = {"sources": [{"path": "foo.py", "excerpt": 42}]}
    with pytest.raises(ValueError, match="'excerpt' must be str or null"):
        extract_context_sources(response)


# ---------------------------------------------------------------------------
# has_expected_path_in_top_k
# ---------------------------------------------------------------------------


def test_top_k_hit_true_k3() -> None:
    result_paths = ["a.py", "b.py", "c.py", "d.py"]
    assert has_expected_path_in_top_k(result_paths, ["b.py"], 3) is True


def test_top_k_hit_false_k3() -> None:
    result_paths = ["a.py", "b.py", "c.py", "d.py"]
    assert has_expected_path_in_top_k(result_paths, ["d.py"], 3) is False


def test_top1_only_checks_first() -> None:
    # b.py is at index 1; top-1 only looks at index 0
    result_paths = ["a.py", "b.py"]
    assert has_expected_path_in_top_k(result_paths, ["b.py"], 1) is False


# ---------------------------------------------------------------------------
# has_context_path_hit
# ---------------------------------------------------------------------------


def test_context_path_hit_true() -> None:
    sources = [ContextSource(path="foo/bar.py", excerpt="text")]
    assert has_context_path_hit(sources, ["foo/bar.py"]) is True


def test_context_path_hit_false() -> None:
    sources = [ContextSource(path="foo/bar.py", excerpt="text")]
    assert has_context_path_hit(sources, ["baz/qux.py"]) is False


# ---------------------------------------------------------------------------
# has_required_terms_hit
# ---------------------------------------------------------------------------


def test_required_terms_hit_true() -> None:
    sources = [ContextSource(path="f.py", excerpt="This calls sync_repository")]
    assert has_required_terms_hit(sources, ["sync_repository"]) is True


def test_required_terms_hit_case_insensitive() -> None:
    sources = [ContextSource(path="f.py", excerpt="calls SYNC_REPOSITORY here")]
    assert has_required_terms_hit(sources, ["sync_repository"]) is True


def test_required_terms_hit_empty_terms() -> None:
    # Empty required_terms_any → not applicable → treated as passed
    sources = [ContextSource(path="f.py", excerpt="anything")]
    assert has_required_terms_hit(sources, []) is True


# ---------------------------------------------------------------------------
# Ratio helpers
# ---------------------------------------------------------------------------


def test_ratio_zero_denominator() -> None:
    assert ratio(1, 0) == 0.0


def test_search_top3_ratio() -> None:
    summary = EvalSummary(
        total_cases=10,
        search_top1_hits=5,
        search_top3_hits=8,
        search_top5_hits=9,
        context_path_hits=7,
        context_required_terms_hits=6,
        context_required_terms_applicable=8,
    )
    assert search_top3_ratio(summary) == pytest.approx(0.8)


def test_context_path_ratio() -> None:
    summary = EvalSummary(
        total_cases=10,
        search_top1_hits=5,
        search_top3_hits=8,
        search_top5_hits=9,
        context_path_hits=7,
        context_required_terms_hits=6,
        context_required_terms_applicable=8,
    )
    assert context_path_ratio(summary) == pytest.approx(0.7)


def test_context_terms_ratio_none_when_no_applicable() -> None:
    summary = EvalSummary(
        total_cases=3,
        search_top1_hits=1,
        search_top3_hits=2,
        search_top5_hits=3,
        context_path_hits=2,
        context_required_terms_hits=0,
        context_required_terms_applicable=0,
    )
    assert context_terms_ratio(summary) is None


# ---------------------------------------------------------------------------
# evaluate_case — central glue function
# ---------------------------------------------------------------------------


def test_evaluate_case_sets_all_flags() -> None:
    case = RepositoryEvalCase(
        id="test",
        query="test query",
        expected_paths=["lore/sync/service.py"],
        required_terms_any=["sync"],
    )
    search_paths = ["lore/sync/service.py", "other.py", "another.py"]
    context_sources = [
        ContextSource(path="lore/sync/service.py", excerpt="calls sync_repository here"),
    ]
    result = evaluate_case(case, search_paths, context_sources)
    assert result.case_id == "test"
    assert result.search_top1_path_hit is True
    assert result.search_top3_path_hit is True
    assert result.search_top5_path_hit is True
    assert result.context_path_hit is True
    assert result.context_required_terms_hit is True
    assert result.context_required_terms_applicable is True


def test_evaluate_case_miss() -> None:
    case = RepositoryEvalCase(
        id="miss",
        query="query with no results",
        expected_paths=["lore/missing.py"],
        required_terms_any=["absent_term"],
    )
    result = evaluate_case(case, search_paths=[], context_sources=[])
    assert result.search_top1_path_hit is False
    assert result.search_top3_path_hit is False
    assert result.context_path_hit is False
    assert result.context_required_terms_hit is False
    assert result.context_required_terms_applicable is True


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def _make_result(
    case_id: str,
    *,
    top1: bool = False,
    top3: bool = False,
    top5: bool = False,
    ctx_path: bool = False,
    terms_hit: bool = True,
    terms_applicable: bool = False,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        query="q",
        expected_paths=["a.py"],
        required_terms_any=[],
        search_paths=[],
        context_sources=[],
        search_top1_path_hit=top1,
        search_top3_path_hit=top3,
        search_top5_path_hit=top5,
        context_path_hit=ctx_path,
        context_required_terms_hit=terms_hit,
        context_required_terms_applicable=terms_applicable,
    )


def test_aggregate_metrics() -> None:
    results = [
        _make_result(
            "c1",
            top1=True,
            top3=True,
            top5=True,
            ctx_path=True,
            terms_hit=True,
            terms_applicable=True,
        ),
        _make_result(
            "c2",
            top1=False,
            top3=True,
            top5=True,
            ctx_path=True,
            terms_hit=False,
            terms_applicable=True,
        ),
        _make_result(
            "c3",
            top1=False,
            top3=False,
            top5=False,
            ctx_path=False,
            terms_hit=True,
            terms_applicable=False,
        ),
    ]
    summary = summarize_results(results)
    assert summary.total_cases == 3
    assert summary.search_top1_hits == 1
    assert summary.search_top3_hits == 2
    assert summary.search_top5_hits == 2
    assert summary.context_path_hits == 2
    assert summary.context_required_terms_hits == 1  # c1 only (c2 applicable but not hit)
    assert summary.context_required_terms_applicable == 2  # c1 + c2


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


def test_thresholds_pass() -> None:
    summary = EvalSummary(
        total_cases=10,
        search_top1_hits=5,
        search_top3_hits=8,  # 80% ≥ 70%
        search_top5_hits=9,
        context_path_hits=8,  # 80% ≥ 70%
        context_required_terms_hits=6,
        context_required_terms_applicable=8,
    )
    assert thresholds_passed(summary, min_top3=0.70, min_context_hit=0.70) is True


def test_thresholds_fail_top3() -> None:
    summary = EvalSummary(
        total_cases=10,
        search_top1_hits=3,
        search_top3_hits=6,  # 60% < 70%
        search_top5_hits=7,
        context_path_hits=8,
        context_required_terms_hits=6,
        context_required_terms_applicable=8,
    )
    assert thresholds_passed(summary, min_top3=0.70, min_context_hit=0.70) is False


def test_thresholds_fail_context() -> None:
    summary = EvalSummary(
        total_cases=10,
        search_top1_hits=5,
        search_top3_hits=8,
        search_top5_hits=9,
        context_path_hits=6,  # 60% < 70%
        context_required_terms_hits=6,
        context_required_terms_applicable=8,
    )
    assert thresholds_passed(summary, min_top3=0.70, min_context_hit=0.70) is False


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def _make_one_case_dataset(
    case_id: str, query: str, paths: list[str], terms: list[str]
) -> RepositoryEvalDataset:
    return RepositoryEvalDataset(
        name="test-eval",
        repository=RepositoryInfo(provider="github", full_name="Isqanderm/lore"),
        cases=[
            RepositoryEvalCase(
                id=case_id,
                query=query,
                expected_paths=paths,
                required_terms_any=terms,
            )
        ],
    )


def test_format_report_pass() -> None:
    dataset = _make_one_case_dataset(
        "case-1", "How does sync work?", ["lore/sync/service.py"], ["sync"]
    )
    result = CaseResult(
        case_id="case-1",
        query="How does sync work?",
        expected_paths=["lore/sync/service.py"],
        required_terms_any=["sync"],
        search_paths=["lore/sync/service.py", "other.py"],
        context_sources=[ContextSource(path="lore/sync/service.py", excerpt="def sync_repository")],
        search_top1_path_hit=True,
        search_top3_path_hit=True,
        search_top5_path_hit=True,
        context_path_hit=True,
        context_required_terms_hit=True,
        context_required_terms_applicable=True,
    )
    summary = summarize_results([result])
    report = format_report(dataset, [result], summary, min_top3=0.70, min_context_hit=0.70)
    assert "test-eval" in report
    assert "github" in report
    assert "Isqanderm/lore" in report
    assert "Cases: 1" in report
    assert "PASS" in report
    assert "Failures" not in report


def test_format_report_shows_failure_section() -> None:
    dataset = _make_one_case_dataset(
        "case-fail", "Does not find anything?", ["lore/missing.py"], ["missing_fn"]
    )
    result = CaseResult(
        case_id="case-fail",
        query="Does not find anything?",
        expected_paths=["lore/missing.py"],
        required_terms_any=["missing_fn"],
        search_paths=["other.py", "another.py"],
        context_sources=[ContextSource(path="other.py", excerpt="some unrelated text")],
        search_top1_path_hit=False,
        search_top3_path_hit=False,
        search_top5_path_hit=False,
        context_path_hit=False,
        context_required_terms_hit=False,
        context_required_terms_applicable=True,
    )
    summary = summarize_results([result])
    report = format_report(dataset, [result], summary, min_top3=0.70, min_context_hit=0.70)
    assert "FAIL" in report
    assert "case-fail" in report
    assert "lore/missing.py" in report
    assert "search_top3_path_hit" in report


def test_format_report_terms_na_when_no_applicable() -> None:
    dataset = _make_one_case_dataset("case-no-terms", "Something?", ["lore/sync/service.py"], [])
    result = CaseResult(
        case_id="case-no-terms",
        query="Something?",
        expected_paths=["lore/sync/service.py"],
        required_terms_any=[],
        search_paths=["lore/sync/service.py"],
        context_sources=[ContextSource(path="lore/sync/service.py", excerpt="text")],
        search_top1_path_hit=True,
        search_top3_path_hit=True,
        search_top5_path_hit=True,
        context_path_hit=True,
        context_required_terms_hit=True,
        context_required_terms_applicable=False,
    )
    summary = summarize_results([result])
    report = format_report(dataset, [result], summary, min_top3=0.70, min_context_hit=0.70)
    assert "n/a" in report
