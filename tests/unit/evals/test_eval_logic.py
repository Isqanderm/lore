from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from evals.repository_retrieval.eval_logic import (
    RepositoryEvalDataset,
    load_dataset,
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
    from pathlib import Path as PathlibPath

    f = PathlibPath(tmp_path) / "eval.json"
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
