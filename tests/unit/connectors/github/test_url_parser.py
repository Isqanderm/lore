import pytest

from lore.connectors.github.models import parse_github_url


def test_parse_https_url() -> None:
    owner, repo = parse_github_url("https://github.com/Isqanderm/lore")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_https_url_with_trailing_slash() -> None:
    owner, repo = parse_github_url("https://github.com/Isqanderm/lore/")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_https_url_with_git_suffix() -> None:
    owner, repo = parse_github_url("https://github.com/Isqanderm/lore.git")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_ssh_url() -> None:
    owner, repo = parse_github_url("git@github.com:Isqanderm/lore.git")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_invalid_url_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://gitlab.com/owner/repo")


def test_parse_missing_repo_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://github.com/Isqanderm")


def test_parse_blob_url_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://github.com/Isqanderm/lore/blob/main/README.md")


def test_parse_tree_url_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://github.com/Isqanderm/lore/tree/main")
