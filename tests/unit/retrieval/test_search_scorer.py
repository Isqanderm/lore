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


def test_tokenize_query_removes_question_stopwords() -> None:
    assert tokenize_query("How does the repository sync lifecycle work?") == [
        "repository",
        "sync",
        "lifecycle",
        "work",
    ]


def test_tokenize_query_keeps_domain_terms() -> None:
    assert tokenize_query(
        "repository document context source service sync version chunk search route api"
    ) == [
        "repository",
        "document",
        "context",
        "source",
        "service",
        "sync",
        "version",
        "chunk",
        "search",
        "route",
        "api",
    ]


def test_tokenize_query_drops_one_character_tokens_and_stopwords() -> None:
    # "a" is both length-1 and a stopword; "x" is length-1; "sync" passes both checks.
    assert tokenize_query("a x sync") == ["sync"]


def test_score_document_returns_zero_when_no_terms_match_anywhere() -> None:
    score = score_document(
        query="repository sync",
        terms=["repository", "sync"],
        path="foo/bar.py",
        content="unrelated content",
    )
    assert score == 0.0


def test_score_document_boosts_path_matches() -> None:
    score = score_document(
        query="repository sync",
        terms=["sync"],
        path="lore/sync/service.py",
        content="",
    )
    assert score > 0


def test_score_document_boosts_basename_matches_more_than_directory_matches() -> None:
    terms = ["import"]

    # "import" appears in both path AND basename (repository_import.py)
    basename_score = score_document(
        query="repository import",
        terms=terms,
        path="lore/ingestion/repository_import.py",
        content="",
    )

    # "import" appears in path directory segment, but NOT in basename (service.py)
    directory_score = score_document(
        query="repository import",
        terms=terms,
        path="lore/import/service.py",
        content="",
    )

    assert basename_score > directory_score


def test_score_document_caps_repeated_content_matches() -> None:
    terms = ["sync"]
    content_10 = " ".join(["sync"] * 10)
    content_20 = " ".join(["sync"] * 20)

    score_10 = score_document(
        query="sync",
        terms=terms,
        path="foo.py",
        content=content_10,
    )
    score_20 = score_document(
        query="sync",
        terms=terms,
        path="foo.py",
        content=content_20,
    )

    assert score_20 == score_10


def test_score_document_exact_phrase_in_path_contributes() -> None:
    # Both paths contain both terms in path and basename.
    # Only the first path contains the literal phrase "repository_import".
    # This isolates the PATH_PHRASE_WEIGHT contribution.
    terms = ["repository", "import"]

    score_with_phrase = score_document(
        query="repository_import",
        terms=terms,
        path="lore/ingestion/repository_import.py",
        content="",
    )

    score_without_phrase = score_document(
        query="repository_import",
        terms=terms,
        path="lore/ingestion/repository/service_import.py",
        content="",
    )

    assert score_with_phrase > score_without_phrase


def test_score_document_exact_phrase_in_content_contributes() -> None:
    score = score_document(
        query="repository sync",
        terms=["repository", "sync"],
        path="foo.py",
        content="this explains repository sync behavior",
    )
    assert score > 0
