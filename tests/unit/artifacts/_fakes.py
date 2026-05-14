from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from lore.schema.repository_artifact import RepositoryArtifact


# ---------------------------------------------------------------------------
# Stub objects (not real ORM/schema — just duck-typed stubs for unit tests)
# ---------------------------------------------------------------------------


class FakeExternalRepository:
    """Minimal stub matching ExternalRepository dataclass fields."""

    def __init__(
        self,
        id: UUID,
        name: str = "my-repo",
        full_name: str = "owner/my-repo",
        provider: str = "github",
        default_branch: str = "main",
        html_url: str = "https://github.com/owner/my-repo",
        connection_id: UUID | None = None,
    ) -> None:
        from uuid import uuid4

        self.id = id
        self.name = name
        self.full_name = full_name
        self.provider = provider
        self.default_branch = default_branch
        self.html_url = html_url
        self.connection_id = connection_id or uuid4()


class FakeRepositorySyncRun:
    """Minimal stub matching RepositorySyncRun dataclass fields."""

    def __init__(
        self,
        id: UUID,
        repository_id: UUID,
        finished_at: datetime | None = None,
        started_at: datetime | None = None,
        status: str = "succeeded",
    ) -> None:
        self.id = id
        self.repository_id = repository_id
        self.finished_at = finished_at or datetime.now(UTC)
        self.started_at = started_at or datetime.now(UTC)
        self.status = status


# ---------------------------------------------------------------------------
# Fake repositories
# ---------------------------------------------------------------------------


class FakeExternalRepositoryRepository:
    """Returns a stub ExternalRepository or None."""

    def __init__(self, repo: FakeExternalRepository | None = None) -> None:
        self._repo = repo

    async def get_by_id(self, id: UUID) -> FakeExternalRepository | None:
        return self._repo


class FakeRepositorySyncRunRepository:
    def __init__(self, latest_succeeded: FakeRepositorySyncRun | None = None) -> None:
        self._latest_succeeded = latest_succeeded

    async def get_latest_succeeded_by_repository(
        self, repository_id: UUID
    ) -> FakeRepositorySyncRun | None:
        return self._latest_succeeded


class FakeDocumentRepository:
    def __init__(self, paths: list[str] | None = None) -> None:
        self._paths: list[str] = paths or []

    async def get_document_paths_by_repository_id(self, repository_id: UUID) -> list[str]:
        return list(self._paths)

    async def get_active_document_paths_by_repository_id(self, repository_id: UUID) -> list[str]:
        return list(self._paths)


class FakeRepositoryArtifactRepository:
    def __init__(self) -> None:
        self._artifact: RepositoryArtifact | None = None

    async def upsert(self, artifact: RepositoryArtifact) -> RepositoryArtifact:
        self._artifact = artifact
        return artifact

    async def get_by_repository_and_type(
        self,
        repository_id: UUID,
        artifact_type: str,
    ) -> RepositoryArtifact | None:
        return self._artifact
