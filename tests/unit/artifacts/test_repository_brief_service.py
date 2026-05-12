from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_brief_service import RepositoryBriefService
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ID = uuid4()
_RUN_ID = uuid4()


def _make_repo(repo_id: UUID = _REPO_ID) -> FakeExternalRepository:
    return FakeExternalRepository(
        id=repo_id,
        name="my-repo",
        full_name="owner/my-repo",
        provider="github",
        default_branch="main",
        html_url="https://github.com/owner/my-repo",
    )


def _make_run(run_id: UUID = _RUN_ID, repo_id: UUID = _REPO_ID) -> FakeRepositorySyncRun:
    return FakeRepositorySyncRun(
        id=run_id,
        repository_id=repo_id,
        finished_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


def _make_service(
    repo: FakeExternalRepository | None = None,
    run: FakeRepositorySyncRun | None = None,
    paths: list[str] | None = None,
    artifact_repo: FakeRepositoryArtifactRepository | None = None,
) -> tuple[RepositoryBriefService, FakeRepositoryArtifactRepository]:
    artifact_repo = artifact_repo or FakeRepositoryArtifactRepository()
    service = RepositoryBriefService(
        external_repository_repo=FakeExternalRepositoryRepository(repo),  # type: ignore[arg-type]
        sync_run_repo=FakeRepositorySyncRunRepository(run),  # type: ignore[arg-type]
        document_repo=FakeDocumentRepository(paths or []),  # type: ignore[arg-type]
        artifact_repo=artifact_repo,  # type: ignore[arg-type]
    )
    return service, artifact_repo


# ---------------------------------------------------------------------------
# generate_brief tests
# ---------------------------------------------------------------------------


async def test_generate_brief_zero_files() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=[])
    result = await service.generate_brief(_REPO_ID)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.is_stale is False
    assert result.content is not None
    assert result.content.stats.total_files == 0


async def test_generate_brief_markdown_file_counts() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=["README.md"])
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.stats.markdown_files == 1


async def test_generate_brief_source_file_counts() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=["src/app.py"])
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.stats.source_files == 1


async def test_generate_brief_config_file_counts() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=["package.json"])
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.stats.config_files == 1


async def test_generate_brief_test_file_counts() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=["tests/test_app.py"])
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.stats.test_files == 1


async def test_generate_brief_important_files_detected() -> None:
    service, _ = _make_service(
        repo=_make_repo(), run=_make_run(), paths=["README.md", "Dockerfile"]
    )
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.signals.has_readme is True
    assert result.content.signals.has_docker is True


async def test_generate_brief_language_counts_sorted() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=["a.py", "b.py", "c.ts"])
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    langs = result.content.languages
    assert langs[0].extension == ".py"
    assert langs[0].count == 2
    assert langs[1].extension == ".ts"
    assert langs[1].count == 1


async def test_generate_brief_source_sync_run_id_stored() -> None:
    run = _make_run()
    service, artifact_repo = _make_service(repo=_make_repo(), run=run)
    result = await service.generate_brief(_REPO_ID)

    assert result.source_sync_run_id == run.id


async def test_generate_brief_is_stale_false() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run())
    result = await service.generate_brief(_REPO_ID)

    assert result.is_stale is False


async def test_generate_brief_idempotent() -> None:
    run = _make_run()
    artifact_repo = FakeRepositoryArtifactRepository()
    service, _ = _make_service(repo=_make_repo(), run=run, artifact_repo=artifact_repo)

    result1 = await service.generate_brief(_REPO_ID)
    result2 = await service.generate_brief(_REPO_ID)

    # Both calls succeed and both see the same sync run
    assert result1.source_sync_run_id == run.id
    assert result2.source_sync_run_id == run.id


async def test_generate_brief_raises_409_when_no_sync_run() -> None:
    service, _ = _make_service(repo=_make_repo(), run=None)

    with pytest.raises(RepositoryNotSyncedError):
        await service.generate_brief(_REPO_ID)


async def test_generate_brief_raises_404_when_no_repository() -> None:
    service, _ = _make_service(repo=None, run=_make_run())

    with pytest.raises(RepositoryNotFoundError):
        await service.generate_brief(_REPO_ID)


# ---------------------------------------------------------------------------
# get_brief tests
# ---------------------------------------------------------------------------


async def test_get_brief_returns_missing_when_no_artifact() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run())
    # No artifact stored — FakeRepositoryArtifactRepository starts empty
    result = await service.get_brief(_REPO_ID)

    assert result.exists is False
    assert result.state == "missing"
    assert result.reason == "brief_not_generated"


async def test_get_brief_returns_fresh_when_same_sync_run() -> None:
    run = _make_run()
    artifact_repo = FakeRepositoryArtifactRepository()
    service, _ = _make_service(repo=_make_repo(), run=run, artifact_repo=artifact_repo)

    await service.generate_brief(_REPO_ID)
    result = await service.get_brief(_REPO_ID)

    assert result.is_stale is False
    assert result.state == "fresh"


async def test_get_brief_returns_stale_after_new_sync_run() -> None:
    original_run = _make_run(run_id=uuid4())
    artifact_repo = FakeRepositoryArtifactRepository()
    service_gen, _ = _make_service(repo=_make_repo(), run=original_run, artifact_repo=artifact_repo)
    await service_gen.generate_brief(_REPO_ID)

    # Now simulate a newer sync run
    new_run = _make_run(run_id=uuid4())
    service_get = RepositoryBriefService(
        external_repository_repo=FakeExternalRepositoryRepository(_make_repo()),  # type: ignore[arg-type]
        sync_run_repo=FakeRepositorySyncRunRepository(new_run),  # type: ignore[arg-type]
        document_repo=FakeDocumentRepository([]),  # type: ignore[arg-type]
        artifact_repo=artifact_repo,  # type: ignore[arg-type]
    )
    result = await service_get.get_brief(_REPO_ID)

    assert result.is_stale is True
    assert result.state == "stale"
    assert result.current_sync_run_id == new_run.id


async def test_get_brief_stale_when_no_latest_run() -> None:
    original_run = _make_run()
    artifact_repo = FakeRepositoryArtifactRepository()
    service_gen, _ = _make_service(repo=_make_repo(), run=original_run, artifact_repo=artifact_repo)
    await service_gen.generate_brief(_REPO_ID)

    # latest_run is now None (e.g. all runs deleted)
    service_get = RepositoryBriefService(
        external_repository_repo=FakeExternalRepositoryRepository(_make_repo()),  # type: ignore[arg-type]
        sync_run_repo=FakeRepositorySyncRunRepository(None),  # type: ignore[arg-type]
        document_repo=FakeDocumentRepository([]),  # type: ignore[arg-type]
        artifact_repo=artifact_repo,  # type: ignore[arg-type]
    )
    result = await service_get.get_brief(_REPO_ID)

    assert result.is_stale is True
    assert result.state == "stale"
    assert result.current_sync_run_id is None


async def test_get_brief_failed_sync_does_not_change_staleness() -> None:
    run = _make_run()
    artifact_repo = FakeRepositoryArtifactRepository()
    service, _ = _make_service(repo=_make_repo(), run=run, artifact_repo=artifact_repo)

    await service.generate_brief(_REPO_ID)
    # A subsequent failed sync run does not change the latest_succeeded
    # The FakeRepositorySyncRunRepository still returns the same successful run
    result = await service.get_brief(_REPO_ID)

    assert result.is_stale is False
    assert result.state == "fresh"


async def test_generate_brief_uppercase_readme_detected() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=["README.MD"])
    # _detect_important_files uses name_lower — "readme.md" matches
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.signals.has_readme is True


async def test_generate_brief_nested_readme_detected() -> None:
    service, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=["docs/README.md"])
    result = await service.generate_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.signals.has_readme is True


async def test_get_brief_deserializes_content() -> None:
    """Content round-trips correctly from generate_brief → upsert → get_brief."""
    run = _make_run()
    artifact_repo = FakeRepositoryArtifactRepository()
    service, _ = _make_service(
        repo=_make_repo(), run=run, paths=["README.md", "src/app.py"], artifact_repo=artifact_repo
    )

    await service.generate_brief(_REPO_ID)
    result = await service.get_brief(_REPO_ID)

    assert result.content is not None
    assert result.content.stats.total_files == 2
    assert result.content.stats.markdown_files == 1
    assert result.content.stats.source_files == 1
    assert result.content.signals.has_readme is True
    assert result.content.repository.full_name == "owner/my-repo"


async def test_get_brief_raises_404_when_no_repository() -> None:
    service, _ = _make_service(repo=None, run=_make_run())

    with pytest.raises(RepositoryNotFoundError):
        await service.get_brief(_REPO_ID)
