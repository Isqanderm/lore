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


def test_extract_context_excerpt_uses_earliest_term_match() -> None:
    content = "aaa second " + "x" * 100 + " first"
    result = extract_context_excerpt(content, ["first", "second"], max_chars=40)
    assert "second" in result.text
    assert result.start <= content.index("second")


def test_extract_context_excerpt_offset_invariant() -> None:
    content = "prefix " * 50 + "needle" + " suffix" * 50
    result = extract_context_excerpt(content, ["needle"], max_chars=200)
    assert content[result.start : result.end] == result.text


def test_extract_context_excerpt_never_exceeds_max_chars() -> None:
    content = "x" * 1000
    result = extract_context_excerpt(content, ["x"], max_chars=200)
    assert result.end - result.start <= 200
    assert len(result.text) <= 200
