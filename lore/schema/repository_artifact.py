from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003, TCH003
from typing import Any
from uuid import UUID  # noqa: TC003, TCH003

ARTIFACT_TYPE_REPOSITORY_BRIEF = "repository_brief"
ARTIFACT_TYPE_REPOSITORY_STRUCTURE = "repository_structure"


@dataclass(frozen=True)
class RepositoryArtifact:
    id: UUID
    repository_id: UUID
    artifact_type: str
    title: str
    content_json: dict[str, Any]
    source_sync_run_id: UUID
    generated_at: datetime
    created_at: datetime
    updated_at: datetime
