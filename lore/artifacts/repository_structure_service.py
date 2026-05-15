from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_structure_models import (
    EntrypointCandidate,
    ManifestEntry,
    RepositoryStructureClassification,
    RepositoryStructureContent,
    RepositoryStructureInfrastructure,
    RepositoryStructureRepositoryInfo,
    RepositoryStructureState,
    RepositoryStructureStats,
    RepositoryStructureSyncInfo,
    RepositoryStructureTree,
    TopLevelDirectoryEntry,
    classify_roots,
    detect_entrypoint_candidates,
    detect_infrastructure,
    detect_manifests,
    get_top_level_directories,
    get_top_level_files,
    normalize_path,
)
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_STRUCTURE, RepositoryArtifact
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


def _content_from_dict(d: dict) -> RepositoryStructureContent:  # type: ignore[type-arg]
    repo_info = d["repository"]
    sync_info = d["sync"]
    tree_info = d["tree"]
    cls_info = d["classification"]
    infra_info = d["infrastructure"]
    stats_info = d["stats"]
    return RepositoryStructureContent(
        repository=RepositoryStructureRepositoryInfo(
            name=repo_info["name"],
            full_name=repo_info["full_name"],
            provider=repo_info["provider"],
            default_branch=repo_info["default_branch"],
            url=repo_info["url"],
        ),
        sync=RepositoryStructureSyncInfo(
            sync_run_id=sync_info["sync_run_id"],
            last_synced_at=sync_info.get("last_synced_at"),
            commit_sha=sync_info.get("commit_sha"),
        ),
        tree=RepositoryStructureTree(
            top_level_directories=[
                TopLevelDirectoryEntry(path=e["path"], files=e["files"])
                for e in tree_info.get("top_level_directories", [])
            ],
            top_level_files=tree_info.get("top_level_files", []),
        ),
        classification=RepositoryStructureClassification(
            source_roots=cls_info.get("source_roots", []),
            test_roots=cls_info.get("test_roots", []),
            docs_roots=cls_info.get("docs_roots", []),
            config_roots=cls_info.get("config_roots", []),
        ),
        manifests=[ManifestEntry(path=e["path"], kind=e["kind"]) for e in d.get("manifests", [])],
        entrypoint_candidates=[
            EntrypointCandidate(path=e["path"], kind=e["kind"])
            for e in d.get("entrypoint_candidates", [])
        ],
        infrastructure=RepositoryStructureInfrastructure(
            docker_files=infra_info.get("docker_files", []),
            ci_files=infra_info.get("ci_files", []),
            migration_dirs=infra_info.get("migration_dirs", []),
        ),
        stats=RepositoryStructureStats(
            total_active_files=stats_info["total_active_files"],
            top_level_directory_count=stats_info["top_level_directory_count"],
            manifest_count=stats_info["manifest_count"],
            entrypoint_candidate_count=stats_info["entrypoint_candidate_count"],
        ),
        schema_version=d.get("schema_version", 1),
        generated_by=d.get("generated_by", "repository_structure_service"),
    )


@dataclass(frozen=True)
class RepositoryStructureServiceResult:
    exists: bool
    state: RepositoryStructureState
    is_stale: bool
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    generated_at: datetime | None = None
    source_sync_run_id: UUID | None = None
    current_sync_run_id: UUID | None = None
    content: RepositoryStructureContent | None = None
    reason: str | None = None


class RepositoryStructureService:
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

    async def generate_structure(self, repository_id: UUID) -> RepositoryStructureServiceResult:
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)
        if latest_run is None:
            raise RepositoryNotSyncedError(repository_id)

        raw_paths = await self._document_repo.get_active_document_paths_by_repository_id(
            repository_id
        )
        normalized = sorted({normalize_path(p) for p in raw_paths if normalize_path(p)})

        tree = RepositoryStructureTree(
            top_level_directories=get_top_level_directories(normalized),
            top_level_files=get_top_level_files(normalized),
        )
        classification = classify_roots(normalized)
        manifests = detect_manifests(normalized)
        entrypoints = detect_entrypoint_candidates(normalized)
        infrastructure = detect_infrastructure(normalized)
        stats = RepositoryStructureStats(
            total_active_files=len(normalized),
            top_level_directory_count=len(tree.top_level_directories),
            manifest_count=len(manifests),
            entrypoint_candidate_count=len(entrypoints),
        )

        content = RepositoryStructureContent(
            repository=RepositoryStructureRepositoryInfo(
                name=repo.name,
                full_name=repo.full_name,
                provider=repo.provider,
                default_branch=repo.default_branch,
                url=repo.html_url,
            ),
            sync=RepositoryStructureSyncInfo(
                sync_run_id=str(latest_run.id),
                last_synced_at=latest_run.finished_at.isoformat()
                if latest_run.finished_at
                else None,
            ),
            tree=tree,
            classification=classification,
            manifests=manifests,
            entrypoint_candidates=entrypoints,
            infrastructure=infrastructure,
            stats=stats,
        )

        now = datetime.now(UTC)
        artifact = RepositoryArtifact(
            id=uuid4(),
            repository_id=repository_id,
            artifact_type=ARTIFACT_TYPE_REPOSITORY_STRUCTURE,
            title=f"Repository Structure: {repo.full_name}",
            content_json=dataclasses.asdict(content),
            source_sync_run_id=latest_run.id,
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        saved = await self._artifact_repo.upsert(artifact)

        return RepositoryStructureServiceResult(
            exists=True,
            state="fresh",
            is_stale=False,
            repository_id=repository_id,
            generated_at=saved.generated_at,
            source_sync_run_id=saved.source_sync_run_id,
            current_sync_run_id=latest_run.id,
            content=content,
        )

    async def get_structure(self, repository_id: UUID) -> RepositoryStructureServiceResult:
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        artifact = await self._artifact_repo.get_by_repository_and_type(
            repository_id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE
        )
        if artifact is None:
            return RepositoryStructureServiceResult(
                exists=False,
                state="missing",
                is_stale=False,
                repository_id=repository_id,
                reason="structure_not_generated",
            )

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)

        if latest_run is None:
            is_stale = True
            state: RepositoryStructureState = "stale"
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

        return RepositoryStructureServiceResult(
            exists=True,
            state=state,
            is_stale=is_stale,
            repository_id=repository_id,
            generated_at=artifact.generated_at,
            source_sync_run_id=artifact.source_sync_run_id,
            current_sync_run_id=current_sync_run_id,
            content=content,
        )
