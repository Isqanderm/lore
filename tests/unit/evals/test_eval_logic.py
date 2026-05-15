from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from evals.repository_retrieval.eval_logic import (
    RepositoryEvalDataset,
    extract_context_sources,
    extract_search_paths,
    load_dataset,
    normalize_path,
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
