# tests/unit/artifacts/test_repository_structure_service.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_structure_service import RepositoryStructureService
from lore.sync.errors import RepositoryNotFoundError
from tests.unit.artifacts._fakes import (
    FakeDocumentRepository,
    FakeExternalRepository,
    FakeExternalRepositoryRepository,
    FakeRepositoryArtifactRepository,
    FakeRepositorySyncRun,
    FakeRepositorySyncRunRepository,
)

pytestmark = pytest.mark.unit

_REPO_ID = uuid4()
_RUN_ID = uuid4()


def _make_repo(repo_id: UUID = _REPO_ID) -> FakeExternalRepository:
    return FakeExternalRepository(
        id=repo_id,
        name="lore",
        full_name="acme/lore",
        provider="github",
        default_branch="main",
        html_url="https://github.com/acme/lore",
    )


def _make_run(run_id: UUID = _RUN_ID, repo_id: UUID = _REPO_ID) -> FakeRepositorySyncRun:
    return FakeRepositorySyncRun(
        id=run_id,
        repository_id=repo_id,
        finished_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
    )


def _make_service(
    repo: FakeExternalRepository | None = None,
    run: FakeRepositorySyncRun | None = None,
    paths: list[str] | None = None,
    artifact_repo: FakeRepositoryArtifactRepository | None = None,
) -> tuple[RepositoryStructureService, FakeRepositoryArtifactRepository]:
    artifact_repo = artifact_repo or FakeRepositoryArtifactRepository()
    svc = RepositoryStructureService(
        external_repository_repo=FakeExternalRepositoryRepository(repo),
        sync_run_repo=FakeRepositorySyncRunRepository(run),
        document_repo=FakeDocumentRepository(paths or []),
        artifact_repo=artifact_repo,
    )
    return svc, artifact_repo


# ---------------------------------------------------------------------------
# generate_structure
# ---------------------------------------------------------------------------


async def test_generate_structure_creates_artifact_from_active_paths() -> None:
    paths = [
        "README.md",
        "pyproject.toml",
        "apps/api/main.py",
        "tests/unit/test_x.py",
    ]
    svc, artifact_repo = _make_service(repo=_make_repo(), run=_make_run(), paths=paths)
    result = await svc.generate_structure(_REPO_ID)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.is_stale is False
    assert result.content is not None
    assert result.content.stats.total_active_files == 4
    assert result.content.stats.manifest_count == 1  # pyproject.toml
    assert result.content.stats.entrypoint_candidate_count == 1  # apps/api/main.py
    # Verify artifact was persisted via the public fake method
    persisted = await artifact_repo.get_by_repository_and_type(_REPO_ID, "repository_structure")
    assert persisted is not None
    assert persisted.artifact_type == "repository_structure"
    assert persisted.source_sync_run_id == _RUN_ID


async def test_generate_structure_empty_paths_is_valid() -> None:
    """A succeeded sync with zero active files must produce a fresh artifact."""
    svc, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=[])
    result = await svc.generate_structure(_REPO_ID)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.content is not None
    assert result.content.stats.total_active_files == 0


async def test_generate_structure_raises_repository_not_found() -> None:
    svc, _ = _make_service(repo=None, run=_make_run())
    with pytest.raises(RepositoryNotFoundError):
        await svc.generate_structure(_REPO_ID)


async def test_generate_structure_raises_not_synced_without_successful_run() -> None:
    svc, _ = _make_service(repo=_make_repo(), run=None)
    with pytest.raises(RepositoryNotSyncedError):
        await svc.generate_structure(_REPO_ID)


# ---------------------------------------------------------------------------
# get_structure
# ---------------------------------------------------------------------------


async def test_get_structure_missing_returns_missing_state() -> None:
    svc, _ = _make_service(repo=_make_repo(), run=_make_run())
    # No artifact stored yet
    result = await svc.get_structure(_REPO_ID)

    assert result.exists is False
    assert result.state == "missing"
    assert result.reason == "structure_not_generated"
    assert result.content is None


async def test_get_structure_fresh_when_source_sync_matches_latest() -> None:
    run = _make_run()
    artifact_repo = FakeRepositoryArtifactRepository()
    svc, _ = _make_service(repo=_make_repo(), run=run, artifact_repo=artifact_repo)

    await svc.generate_structure(_REPO_ID)
    result = await svc.get_structure(_REPO_ID)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.is_stale is False


async def test_get_structure_stale_when_latest_sync_differs() -> None:
    original_run = _make_run(run_id=uuid4())
    artifact_repo = FakeRepositoryArtifactRepository()

    svc_gen, _ = _make_service(repo=_make_repo(), run=original_run, artifact_repo=artifact_repo)
    await svc_gen.generate_structure(_REPO_ID)

    new_run = _make_run(run_id=uuid4())
    svc_get = RepositoryStructureService(
        external_repository_repo=FakeExternalRepositoryRepository(_make_repo()),
        sync_run_repo=FakeRepositorySyncRunRepository(new_run),
        document_repo=FakeDocumentRepository([]),
        artifact_repo=artifact_repo,
    )
    result = await svc_get.get_structure(_REPO_ID)

    assert result.is_stale is True
    assert result.state == "stale"
    assert result.current_sync_run_id == new_run.id


async def test_get_structure_deserializes_content_round_trip() -> None:
    paths = ["README.md", "apps/api/main.py", "tests/unit/test_x.py"]
    artifact_repo = FakeRepositoryArtifactRepository()
    svc, _ = _make_service(
        repo=_make_repo(), run=_make_run(), paths=paths, artifact_repo=artifact_repo
    )

    await svc.generate_structure(_REPO_ID)
    result = await svc.get_structure(_REPO_ID)

    assert result.content is not None
    assert result.content.stats.total_active_files == 3
    assert result.content.repository.full_name == "acme/lore"
    assert result.content.schema_version == 1
    assert result.content.generated_by == "repository_structure_service"


async def test_get_structure_raises_repository_not_found() -> None:
    svc, _ = _make_service(repo=None, run=_make_run())
    with pytest.raises(RepositoryNotFoundError):
        await svc.get_structure(_REPO_ID)
