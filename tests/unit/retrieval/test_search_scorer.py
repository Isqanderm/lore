from __future__ import annotations

import pytest

from lore.retrieval.service import extract_snippet, score_document, tokenize_query

pytestmark = pytest.mark.unit


def test_tokenize_query_splits_on_non_word_chars() -> None:
    assert tokenize_query("github sync") == ["github", "sync"]


def test_tokenize_query_drops_single_char_tokens() -> None:
    assert tokenize_query("a b go") == ["go"]


def test_tokenize_query_returns_empty_list_for_blank() -> None:
    assert tokenize_query("") == []


def test_score_document_returns_zero_when_no_match() -> None:
    score = score_document("sync", ["sync"], "README.md", "hello world")
    assert score == 0.0


def test_score_document_term_in_path_gives_positive_score() -> None:
    score = score_document("sync", ["sync"], "lore/sync/service.py", "unrelated")
    assert score > 0.0


def test_score_document_term_in_content_gives_positive_score() -> None:
    score = score_document("sync", ["sync"], "README.md", "this is about sync lifecycle")
    assert score > 0.0


def test_score_document_phrase_in_path_scores_higher_than_term_only() -> None:
    # Use hyphen so the phrase is a literal substring of the path.
    # Underscore is a word char — "sync_service" does NOT contain "sync service".
    phrase_score = score_document(
        "sync-service", ["sync", "service"], "lore/sync-service/main.py", ""
    )
    content_only_score = score_document(
        "sync-service", ["sync", "service"], "no_match.py", "sync and service here"
    )
    assert phrase_score > content_only_score


def test_score_document_phrase_in_content_scores_higher_than_separated_terms() -> None:
    phrase_score = score_document(
        "sync lifecycle", ["sync", "lifecycle"], "other.py", "sync lifecycle here"
    )
    separated_score = score_document(
        "sync lifecycle", ["sync", "lifecycle"], "other.py", "sync and lifecycle separately"
    )
    assert phrase_score > separated_score


def test_score_document_clamped_to_one() -> None:
    content = " ".join(["sync"] * 100)
    score = score_document("sync", ["sync"], "sync/sync/sync.py", content)
    assert score <= 1.0


def test_score_document_none_content_does_not_crash_and_scores_path() -> None:
    score = score_document("sync", ["sync"], "lore/sync/service.py", None)
    assert score > 0.0


def test_extract_snippet_centers_on_first_matched_term() -> None:
    content = "a" * 100 + "TARGET" + "b" * 200
    snippet = extract_snippet(content, ["target"])
    assert "TARGET" in snippet


def test_extract_snippet_adds_ellipsis_prefix_when_match_is_deep() -> None:
    content = "x" * 300 + "needle" + "x" * 300
    snippet = extract_snippet(content, ["needle"])
    assert snippet.startswith("...")


def test_extract_snippet_adds_ellipsis_suffix_when_content_continues() -> None:
    content = "needle" + "x" * 300
    snippet = extract_snippet(content, ["needle"])
    assert snippet.endswith("...")


def test_extract_snippet_returns_beginning_when_no_term_match() -> None:
    content = "Hello world " * 30
    snippet = extract_snippet(content, ["notfound"])
    assert snippet.startswith("Hello world")
    assert len(snippet) <= 244  # 240 chars + possible "..."


def test_extract_snippet_returns_empty_for_none_content() -> None:
    assert extract_snippet(None, ["term"]) == ""


def test_extract_snippet_returns_empty_for_empty_string() -> None:
    assert extract_snippet("", ["term"]) == ""
