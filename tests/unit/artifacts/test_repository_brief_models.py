from __future__ import annotations

import pytest

from lore.artifacts.repository_brief_models import (
    MARKDOWN_EXTENSIONS,
    SOURCE_EXTENSIONS,
    categorize_paths,
    detect_important_files,
    detect_signals,
    get_language_counts,
)

pytestmark = pytest.mark.unit


def test_markdown_extensions_contains_md() -> None:
    assert ".md" in MARKDOWN_EXTENSIONS
    assert ".mdx" in MARKDOWN_EXTENSIONS


def test_source_extensions_contains_python() -> None:
    assert ".py" in SOURCE_EXTENSIONS
    assert ".ts" in SOURCE_EXTENSIONS


def test_categorize_empty_paths() -> None:
    result = categorize_paths([])
    assert result.total_files == 0
    assert result.markdown_files == 0
    assert result.source_files == 0
    assert result.config_files == 0
    assert result.test_files == 0


def test_categorize_markdown_file() -> None:
    result = categorize_paths(["docs/README.md"])
    assert result.markdown_files == 1
    assert result.total_files == 1


def test_categorize_source_file() -> None:
    result = categorize_paths(["src/app.py"])
    assert result.source_files == 1


def test_categorize_config_file_package_json() -> None:
    result = categorize_paths(["package.json"])
    assert result.config_files == 1


def test_categorize_config_file_dockerfile() -> None:
    result = categorize_paths(["Dockerfile"])
    assert result.config_files == 1


def test_categorize_test_file_by_path() -> None:
    result = categorize_paths(["tests/test_app.py"])
    assert result.test_files == 1


def test_categorize_test_file_by_stem_prefix() -> None:
    result = categorize_paths(["src/test_utils.py"])
    assert result.test_files == 1


def test_categorize_test_file_by_stem_suffix() -> None:
    result = categorize_paths(["src/utils_test.py"])
    assert result.test_files == 1


def test_categorize_file_in_multiple_categories() -> None:
    # A test file that is also a source file — both counts increment
    result = categorize_paths(["tests/test_app.py"])
    assert result.source_files == 1
    assert result.test_files == 1


def test_categorize_unsupported_extension_does_not_error() -> None:
    result = categorize_paths(["some/file.xyz"])
    assert result.total_files == 1
    assert result.source_files == 0
    assert result.markdown_files == 0


def test_detect_important_files_readme() -> None:
    files = detect_important_files(["README.md", "src/app.py"])
    assert any(f.path == "README.md" and f.kind == "readme" for f in files)


def test_detect_important_files_case_insensitive() -> None:
    files = detect_important_files(["readme.md"])
    assert any(f.kind == "readme" for f in files)


def test_detect_important_files_nested_readme() -> None:
    files = detect_important_files(["docs/README.md"])
    assert any(f.kind == "readme" for f in files)


def test_detect_important_files_ci_config() -> None:
    files = detect_important_files([".github/workflows/ci.yml"])
    assert any(f.kind == "ci_config" for f in files)


def test_detect_important_files_dockerfile() -> None:
    files = detect_important_files(["Dockerfile"])
    assert any(f.kind == "docker" for f in files)


def test_detect_important_files_pyproject() -> None:
    files = detect_important_files(["pyproject.toml"])
    assert any(f.kind == "package_manifest" for f in files)


def test_detect_signals_has_readme() -> None:
    files = detect_important_files(["README.md"])
    signals = detect_signals(files)
    assert signals.has_readme is True
    assert signals.has_tests is False


def test_detect_signals_has_docker() -> None:
    files = detect_important_files(["Dockerfile"])
    signals = detect_signals(files)
    assert signals.has_docker is True


def test_detect_signals_has_ci() -> None:
    files = detect_important_files([".github/workflows/ci.yml"])
    signals = detect_signals(files)
    assert signals.has_ci is True


def test_detect_signals_has_tests_from_stats() -> None:
    stats = categorize_paths(["tests/test_app.py"])
    important_files = detect_important_files(["tests/test_app.py"])
    signals = detect_signals(important_files, stats)
    assert signals.has_tests is True


def test_get_language_counts_empty() -> None:
    result = get_language_counts([])
    assert result == []


def test_get_language_counts_sorted_desc() -> None:
    paths = ["a.py", "b.py", "c.ts"]
    result = get_language_counts(paths)
    assert result[0].extension == ".py"
    assert result[0].count == 2
    assert result[1].extension == ".ts"
    assert result[1].count == 1


def test_get_language_counts_includes_all_extensions() -> None:
    result = get_language_counts(["file.xyz"])
    # All extensions should be counted, unknown ones too
    assert len(result) == 1
    assert result[0].extension == ".xyz"
