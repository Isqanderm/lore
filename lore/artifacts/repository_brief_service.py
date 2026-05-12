from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_brief_models import (
    ImportantFileEntry,
    LanguageEntry,
    RepositoryBriefContent,
    RepositoryBriefRepositoryInfo,
    RepositoryBriefSignals,
    RepositoryBriefState,
    RepositoryBriefStats,
    RepositoryBriefSyncInfo,
    _categorize_paths,
    _detect_important_files,
    _detect_signals,
    _get_language_counts,
)
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_BRIEF, RepositoryArtifact
from lore.sync.errors import RepositoryNotFoundError

if TYPE_CHECKING:
    from lore.infrastructure.db.repositories.document import DocumentRepository
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.infrastructure.db.repositories.repository_artifact import (
        RepositoryArtifactRepository,
    )
    from lore.infrastructure.db.repositories.repository_sync_run import (
        RepositorySyncRunRepository,
    )


def _content_from_dict(d: dict) -> RepositoryBriefContent:  # type: ignore[type-arg]
    repo_info = d["repository"]
    sync_info = d["sync"]
    stats_info = d["stats"]
    return RepositoryBriefContent(
        repository=RepositoryBriefRepositoryInfo(
            name=repo_info["name"],
            full_name=repo_info["full_name"],
            provider=repo_info["provider"],
            default_branch=repo_info["default_branch"],
            url=repo_info["url"],
        ),
        sync=RepositoryBriefSyncInfo(
            sync_run_id=sync_info["sync_run_id"],
            last_synced_at=sync_info.get("last_synced_at"),
            commit_sha=sync_info.get("commit_sha"),
        ),
        stats=RepositoryBriefStats(
            total_files=stats_info["total_files"],
            markdown_files=stats_info["markdown_files"],
            source_files=stats_info["source_files"],
            config_files=stats_info["config_files"],
            test_files=stats_info["test_files"],
        ),
        languages=[
            LanguageEntry(extension=entry["extension"], count=entry["count"])
            for entry in d.get("languages", [])
        ],
        important_files=[
            ImportantFileEntry(path=entry["path"], kind=entry["kind"])
            for entry in d.get("important_files", [])
        ],
        signals=RepositoryBriefSignals(
            has_readme=d["signals"]["has_readme"],
            has_tests=d["signals"]["has_tests"],
            has_docker=d["signals"]["has_docker"],
            has_ci=d["signals"]["has_ci"],
            has_package_manifest=d["signals"]["has_package_manifest"],
        ),
        schema_version=d.get("schema_version", 1),
        generated_by=d.get("generated_by", "repository_brief_service"),
    )


class RepositoryBriefServiceResult:
    __slots__ = (
        "exists",
        "state",
        "is_stale",
        "repository_id",
        "artifact_type",
        "generated_at",
        "source_sync_run_id",
        "current_sync_run_id",
        "content",
        "reason",
    )

    def __init__(
        self,
        *,
        exists: bool,
        state: RepositoryBriefState,
        is_stale: bool,
        repository_id: UUID,
        artifact_type: str = ARTIFACT_TYPE_REPOSITORY_BRIEF,
        generated_at: datetime | None = None,
        source_sync_run_id: UUID | None = None,
        current_sync_run_id: UUID | None = None,
        content: RepositoryBriefContent | None = None,
        reason: str | None = None,
    ) -> None:
        self.exists = exists
        self.state = state
        self.is_stale = is_stale
        self.repository_id = repository_id
        self.artifact_type = artifact_type
        self.generated_at = generated_at
        self.source_sync_run_id = source_sync_run_id
        self.current_sync_run_id = current_sync_run_id
        self.content = content
        self.reason = reason


class RepositoryBriefService:
    def __init__(
        self,
        external_repository_repo: ExternalRepositoryRepository,
        sync_run_repo: RepositorySyncRunRepository,
        document_repo: DocumentRepository,
        artifact_repo: RepositoryArtifactRepository,
    ) -> None:
        self._ext_repo_repo = external_repository_repo
        self._sync_run_repo = sync_run_repo
        self._document_repo = document_repo
        self._artifact_repo = artifact_repo

    async def generate_brief(self, repository_id: UUID) -> RepositoryBriefServiceResult:
        """Generate (or regenerate) a repository brief and persist it."""
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)
        if latest_run is None:
            raise RepositoryNotSyncedError(repository_id)

        paths = await self._document_repo.get_document_paths_by_repository_id(repository_id)

        stats = _categorize_paths(paths)
        important_files = _detect_important_files(paths)
        signals = _detect_signals(important_files, stats)
        languages = _get_language_counts(paths)

        content = RepositoryBriefContent(
            repository=RepositoryBriefRepositoryInfo(
                name=repo.name,
                full_name=repo.full_name,
                provider=repo.provider,
                default_branch=repo.default_branch,
                url=repo.html_url,
            ),
            sync=RepositoryBriefSyncInfo(
                sync_run_id=str(latest_run.id),
                last_synced_at=latest_run.finished_at,
            ),
            stats=stats,
            languages=languages,
            important_files=important_files,
            signals=signals,
            schema_version=1,
            generated_by="repository_brief_service",
        )

        now = datetime.now(UTC)
        artifact = RepositoryArtifact(
            id=uuid4(),
            repository_id=repository_id,
            artifact_type=ARTIFACT_TYPE_REPOSITORY_BRIEF,
            title=f"Repository Brief: {repo.full_name}",
            content_json=dataclasses.asdict(content),
            source_sync_run_id=latest_run.id,
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        saved = await self._artifact_repo.upsert(artifact)

        return RepositoryBriefServiceResult(
            exists=True,
            state="fresh",
            is_stale=False,
            repository_id=repository_id,
            generated_at=saved.generated_at,
            source_sync_run_id=saved.source_sync_run_id,
            current_sync_run_id=latest_run.id,
            content=content,
        )

    async def get_brief(self, repository_id: UUID) -> RepositoryBriefServiceResult:
        """Return the current brief for a repository, with freshness information."""
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        artifact = await self._artifact_repo.get_by_repository_and_type(
            repository_id, ARTIFACT_TYPE_REPOSITORY_BRIEF
        )
        if artifact is None:
            return RepositoryBriefServiceResult(
                exists=False,
                state="missing",
                is_stale=False,
                repository_id=repository_id,
                reason="brief_not_generated",
            )

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)

        if latest_run is None:
            is_stale = True
            state: RepositoryBriefState = "stale"
            current_sync_run_id = None
        elif artifact.source_sync_run_id != latest_run.id:
            is_stale = True
            state = "stale"
            current_sync_run_id = latest_run.id
        else:
            is_stale = False
            state = "fresh"
            current_sync_run_id = latest_run.id

        content = _content_from_dict(artifact.content_json)

        return RepositoryBriefServiceResult(
            exists=True,
            state=state,
            is_stale=is_stale,
            repository_id=repository_id,
            generated_at=artifact.generated_at,
            source_sync_run_id=artifact.source_sync_run_id,
            current_sync_run_id=current_sync_run_id,
            content=content,
        )
