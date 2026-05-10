import pytest
from uuid import uuid4
from datetime import datetime, timezone

from lore.schema.source import Source, SourceType


def test_source_is_frozen() -> None:
    s = Source(
        id=uuid4(),
        source_type_raw="git",
        source_type_canonical=SourceType.GIT_REPO,
        origin="https://github.com/example/repo",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        s.origin = "mutated"  # type: ignore[misc]


def test_source_type_values() -> None:
    assert SourceType.GIT_REPO == "git_repo"
    assert SourceType.UNKNOWN == "unknown"
