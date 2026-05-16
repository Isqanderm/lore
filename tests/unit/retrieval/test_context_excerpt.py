from __future__ import annotations

import pytest

from lore.retrieval.service import ContextExcerpt, extract_context_excerpt

pytestmark = pytest.mark.unit


def test_extract_context_excerpt_none_content() -> None:
    result = extract_context_excerpt(None, ["term"], max_chars=100)
    assert result == ContextExcerpt(text="", start=0, end=0)


def test_extract_context_excerpt_empty_content() -> None:
    result = extract_context_excerpt("", ["term"], max_chars=100)
    assert result == ContextExcerpt(text="", start=0, end=0)


def test_extract_context_excerpt_max_chars_zero() -> None:
    result = extract_context_excerpt("some content here", ["content"], max_chars=0)
    assert result == ContextExcerpt(text="", start=0, end=0)


def test_extract_context_excerpt_returns_beginning_when_no_term_match() -> None:
    content = "hello world " * 20
    result = extract_context_excerpt(content, ["notfound"], max_chars=40)
    assert result.start == 0
    assert result.text == content[:40]


def test_extract_context_excerpt_centers_on_matched_term() -> None:
    content = "a" * 200 + "TARGET" + "b" * 200
    result = extract_context_excerpt(content, ["target"], max_chars=100)
    assert "TARGET" in result.text


def test_extract_context_excerpt_tie_breaks_to_earlier_equivalent_window() -> None:
    content = "alpha beta " + ("x" * 300) + "alpha beta"

    result = extract_context_excerpt(content, ["alpha", "beta"], max_chars=50)

    assert result.start == 0
    assert "alpha beta" in result.text


def test_extract_context_excerpt_prefers_dense_term_window_over_earliest_match() -> None:
    content = (
        "repository appears early. "
        + ("x" * 500)
        + " build_repository_context excerpt_chars max_chars "
        + ("y" * 500)
    )

    result = extract_context_excerpt(
        content,
        ["repository", "context", "excerpt_chars", "max_chars"],
        max_chars=120,
    )

    early_repository_index = content.index("repository")
    dense_cluster_index = content.index("build_repository_context")

    assert "build_repository_context" in result.text
    assert "excerpt_chars" in result.text
    assert "max_chars" in result.text
    assert result.start > early_repository_index  # did NOT pick earliest
    assert result.start <= dense_cluster_index  # window reached the dense cluster


def test_extract_context_excerpt_offset_invariant() -> None:
    content = "prefix " * 50 + "needle" + " suffix" * 50
    result = extract_context_excerpt(content, ["needle"], max_chars=200)
    assert content[result.start : result.end] == result.text


def test_extract_context_excerpt_never_exceeds_max_chars() -> None:
    content = "x" * 1000
    result = extract_context_excerpt(content, ["x"], max_chars=200)
    assert result.end - result.start <= 200
    assert len(result.text) <= 200


def test_extract_context_excerpt_case_insensitive_matching() -> None:
    content = ("prefix " * 50) + "TARGET TERM" + (" suffix" * 50)

    result = extract_context_excerpt(content, ["target", "term"], max_chars=100)

    assert "TARGET TERM" in result.text


def test_extract_context_excerpt_clamps_window_near_end_of_content() -> None:
    content = ("x" * 200) + "needle"

    result = extract_context_excerpt(content, ["needle"], max_chars=50)

    assert "needle" in result.text
    assert result.end == len(content)
    assert result.end - result.start <= 50
    assert content[result.start : result.end] == result.text


def test_extract_context_excerpt_empty_terms() -> None:
    content = "hello world " * 10
    result = extract_context_excerpt(content, [], max_chars=40)
    assert result.start == 0
    assert result.text == content[:40]
    assert content[result.start : result.end] == result.text
