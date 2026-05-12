from dataclasses import FrozenInstanceError

import pytest

from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF, RepositoryArtifact


def test_artifact_type_constant() -> None:
    assert ARTIFACT_TYPE_REPOSITORY_BRIEF == "repository_brief"


def test_repository_artifact_is_frozen() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    artifact = RepositoryArtifact(
        id=uuid4(),
        repository_id=uuid4(),
        artifact_type=ARTIFACT_TYPE_REPOSITORY_BRIEF,
        title="Test",
        content_json={"schema_version": 1},
        source_sync_run_id=uuid4(),
        generated_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(FrozenInstanceError):
        artifact.artifact_type = "other"  # type: ignore[misc]
