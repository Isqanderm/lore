from datetime import UTC, datetime
from uuid import uuid4

import pytest

from lore.schema.source import Source, SourceType


def test_source_is_frozen() -> None:
    s = Source(
        id=uuid4(),
        source_type_raw="git",
        source_type_canonical=SourceType.GIT_REPO,
        origin="https://github.com/example/repo",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(AttributeError):
        s.origin = "mutated"  # type: ignore[misc]


def test_source_type_values() -> None:
    assert SourceType.GIT_REPO.value == "git_repo"
    assert SourceType.UNKNOWN.value == "unknown"
