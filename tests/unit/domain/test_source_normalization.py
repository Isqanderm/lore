import pytest
from lore.domain.source import normalize_source_type
from lore.schema.source import SourceType


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("git_repo", SourceType.GIT_REPO),
    ("git", SourceType.GIT_REPO),
    ("github", SourceType.GIT_REPO),
    ("gitlab", SourceType.GIT_REPO),
    ("markdown", SourceType.MARKDOWN),
    ("md", SourceType.MARKDOWN),
    ("adr", SourceType.ADR),
    ("architectural_decision", SourceType.ADR),
    ("slack", SourceType.SLACK),
    ("confluence", SourceType.CONFLUENCE),
    ("wiki", SourceType.CONFLUENCE),
    ("totally_unknown_source", SourceType.UNKNOWN),
    ("", SourceType.UNKNOWN),
    ("  GIT  ", SourceType.GIT_REPO),
])
def test_normalize_source_type(raw: str, expected: SourceType) -> None:
    assert normalize_source_type(raw) == expected
