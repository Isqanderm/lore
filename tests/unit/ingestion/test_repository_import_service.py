"""Unit tests for RepositoryImportService orchestration.

No DB, no HTTP, no real connector calls past inspect_resource.
Verifies:
- import delegates to sync_service.sync_repository(trigger="import", mode="full")
- ImportResult fields are built from RepositorySyncResult (including versions_skipped)
- connector.full_sync() is never called directly
- ConnectorNotFoundError propagates to caller
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.errors import ConnectorNotFoundError
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
)
from lore.connector_sdk.registry import ConnectorRegistry
from lore.ingestion.repository_import import RepositoryImportService
from lore.sync.models import RepositorySyncResult

pytestmark = pytest.mark.unit

_CONN_ID: UUID = uuid4()
_REPO_ID: UUID = uuid4()
_SYNC_RUN_ID: UUID = uuid4()


# ── Fakes ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeConnection:
    id: UUID


@dataclass
class _FakeRepo:
    id: UUID


class _FakeExtConnectionRepo:
    async def get_or_create_env_pat(self, *, provider: str) -> _FakeConnection:
        return _FakeConnection(id=_CONN_ID)


class _FakeExtRepositoryRepo:
    async def get_or_create(self, *, connection_id: UUID, draft: Any) -> _FakeRepo:
        return _FakeRepo(id=_REPO_ID)


class FakeRepositorySyncService:
    """Returns a real RepositorySyncResult so field mismatches are caught at import time."""

    def __init__(self, result: RepositorySyncResult) -> None:
        self.result = result
        self.calls: list[tuple[UUID, str, str]] = []

    async def sync_repository(
        self,
        repository_id: UUID,
        trigger: str = "manual",
        mode: str = "full",
    ) -> RepositorySyncResult:
        self.calls.append((repository_id, trigger, mode))
        return self.result


class _OkConnector(BaseConnector):
    """Connector whose full_sync() raises AssertionError — guards against direct calls."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="github",
            display_name="OK",
            version="0.0.1",
            capabilities=ConnectorCapabilities(
                supports_full_sync=True,
                supports_incremental_sync=False,
                supports_webhooks=False,
                supports_repository_tree=False,
                supports_files=True,
                supports_issues=False,
                supports_pull_requests=False,
                supports_comments=False,
                supports_releases=False,
                supports_permissions=False,
                object_types=("github.file",),
            ),
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider="github",
            owner="acme",
            name="myrepo",
            full_name="acme/myrepo",
            default_branch="main",
            html_url="https://github.com/acme/myrepo",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raise AssertionError("RepositoryImportService must not call connector.full_sync() directly")

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return []


def _make_sync_result(**overrides: Any) -> RepositorySyncResult:
    defaults: dict[str, Any] = dict(
        sync_run_id=_SYNC_RUN_ID,
        repository_id=_REPO_ID,
        status="succeeded",
        trigger="import",
        mode="full",
        raw_objects_processed=1,
        documents_created=1,
        versions_created=1,
        versions_skipped=0,
        warnings=[],
    )
    return RepositorySyncResult(**{**defaults, **overrides})


def _make_svc(fake_sync: FakeRepositorySyncService) -> RepositoryImportService:
    registry = ConnectorRegistry()
    registry.register(_OkConnector())
    return RepositoryImportService(
        registry=registry,
        ext_connection_repo=_FakeExtConnectionRepo(),
        ext_repository_repo=_FakeExtRepositoryRepo(),
        sync_service=fake_sync,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_import_delegates_to_sync_service_with_import_trigger() -> None:
    fake_sync = FakeRepositorySyncService(_make_sync_result())
    svc = _make_svc(fake_sync)

    await svc.import_repository("https://github.com/acme/myrepo", "github")

    assert len(fake_sync.calls) == 1
    repo_id, trigger, mode = fake_sync.calls[0]
    assert repo_id == _REPO_ID
    assert trigger == "import"
    assert mode == "full"


async def test_import_returns_sync_result_fields() -> None:
    sync_result = _make_sync_result(
        status="succeeded",
        raw_objects_processed=5,
        documents_created=3,
        versions_created=2,
        versions_skipped=1,
        warnings=["a note"],
    )
    svc = _make_svc(FakeRepositorySyncService(sync_result))

    result = await svc.import_repository("https://github.com/acme/myrepo", "github")

    assert result.status == "succeeded"
    assert result.sync_run_id == _SYNC_RUN_ID
    assert result.repository_id == _REPO_ID
    assert result.connector_id == "github"
    assert result.report.raw_objects_processed == 5
    assert result.report.documents_created == 3
    assert result.report.versions_created == 2
    assert result.report.versions_skipped == 1  # must be passed through
    assert result.report.warnings == ["a note"]


async def test_import_does_not_call_full_sync_directly() -> None:
    # _OkConnector.full_sync() raises AssertionError.
    # FakeRepositorySyncService never calls full_sync.
    # If this completes without error, import_repository never touched connector.full_sync().
    fake_sync = FakeRepositorySyncService(_make_sync_result())
    svc = _make_svc(fake_sync)

    await svc.import_repository("https://github.com/acme/myrepo", "github")


async def test_import_connector_not_found_propagates() -> None:
    registry = ConnectorRegistry()  # empty — no connectors registered
    fake_sync = FakeRepositorySyncService(_make_sync_result())
    svc = RepositoryImportService(
        registry=registry,
        ext_connection_repo=_FakeExtConnectionRepo(),
        ext_repository_repo=_FakeExtRepositoryRepo(),
        sync_service=fake_sync,
    )

    with pytest.raises(ConnectorNotFoundError):
        await svc.import_repository("https://github.com/acme/myrepo", "nonexistent")
