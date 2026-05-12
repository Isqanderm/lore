# tests/integration/connectors/test_sync_api.py
"""POST /api/v1/repositories/{id}/sync and GET /sync-runs — integration tests.

Each test is independent: uses a unique owner_suffix (uuid4 slice) to avoid
shared state between tests. No reliance on execution order.
Provider id "fake-sync" is distinct from "fake" used in test_import_api.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
)
from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PROVIDER_ID = "fake-sync"


class _FakeSyncConnector(BaseConnector):
    """Fake connector for sync tests.

    owner_suffix makes provider/external_id/external_url unique per test.
    Within a single test, these identifiers stay stable across sync calls —
    only content and content_hash change — so repeat syncs hit the same
    Document and ExternalObject rows (required for idempotency tests C/D).
    """

    def __init__(
        self,
        owner_suffix: str = "default",
        content: str = "# Hello",
        raise_on_sync: Exception | None = None,
    ) -> None:
        self._suffix = owner_suffix
        self._content = content
        self._raise_on_sync = raise_on_sync

    # ── derived identifiers ───────────────────────────────────────────────────

    @property
    def _owner(self) -> str:
        return f"sync-org-{self._suffix}"

    @property
    def _repo(self) -> str:
        return f"sync-repo-{self._suffix}"

    @property
    def _full_name(self) -> str:
        return f"{self._owner}/{self._repo}"

    @property
    def _external_id(self) -> str:
        return f"{self._full_name}:file:README.md"

    @property
    def _external_url(self) -> str:
        return f"https://example.com/{self._full_name}/blob/abc/README.md"

    @property
    def _html_url(self) -> str:
        return f"https://example.com/{self._full_name}"

    # ── BaseConnector interface ───────────────────────────────────────────────

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id=PROVIDER_ID,
            display_name="Fake Sync",
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
            provider=PROVIDER_ID,
            owner=self._owner,
            name=self._repo,
            full_name=self._full_name,
            default_branch="main",
            html_url=self._html_url,
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        if self._raise_on_sync is not None:
            raise self._raise_on_sync

        payload = {"path": "README.md", "owner": self._owner, "repo": self._repo}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw = RawExternalObject(
            provider=PROVIDER_ID,
            object_type="github.file",
            external_id=self._external_id,
            external_url=self._external_url,
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
            content=self._content,
            content_hash="sha256:" + hashlib.sha256(self._content.encode()).hexdigest(),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={
                "commit_sha": "abc123",
                "path": "README.md",
                "owner": self._owner,
                "repo": self._repo,
                "branch": "main",
            },
        )
        return SyncResult(connector_id=PROVIDER_ID, raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        # Intentionally reuses GitHubNormalizer because fake-sync emits github.file-shaped objects.
        return GitHubNormalizer().normalize(raw)


# ── helpers ───────────────────────────────────────────────────────────────────


async def _import_repo(
    app: FastAPI,
    client: AsyncClient,
    owner_suffix: str,
    content: str = "# Hello",
) -> UUID:
    """Import a fresh repository with the given suffix. Returns repository_id."""
    connector = _FakeSyncConnector(owner_suffix=owner_suffix, content=content)
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(
        "/api/v1/repositories/import",
        json={"url": connector._html_url, "connector_id": PROVIDER_ID},
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()["repository_id"])


async def _sync(
    app: FastAPI,
    client: AsyncClient,
    repo_id: UUID,
    owner_suffix: str,
    content: str = "# Hello",
    failing: bool = False,
) -> tuple[int, dict[str, Any]]:
    """POST /sync for repo_id. Returns (status_code, body)."""
    registry = ConnectorRegistry()
    if failing:
        registry.register(
            _FakeSyncConnector(
                owner_suffix=owner_suffix,
                raise_on_sync=RuntimeError("connector boom"),
            )
        )
    else:
        registry.register(_FakeSyncConnector(owner_suffix=owner_suffix, content=content))
    app.state.connector_registry = registry
    resp = await client.post(f"/api/v1/repositories/{repo_id}/sync")
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


# ── A ─────────────────────────────────────────────────────────────────────────


async def test_a_sync_endpoint_returns_200(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """Sync an existing imported repo → 200, sync_run created, status=succeeded."""
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)
    status, body = await _sync(app_with_db, app_client_with_db, repo_id, owner_suffix=suffix)

    assert status == 200
    assert body["status"] == "succeeded"
    assert body["trigger"] == "manual"
    assert body["mode"] == "full"
    assert UUID(body["sync_run_id"])
    assert UUID(body["repository_id"]) == repo_id
    assert "raw_objects_processed" in body
    assert "documents_created" in body
    assert "versions_created" in body
    assert "versions_skipped" in body
    assert "warnings" in body


# ── B ─────────────────────────────────────────────────────────────────────────


async def test_b_sync_does_not_create_duplicate_repository(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Sync must not create a new external_repository row for the same provider+full_name."""
    from sqlalchemy import func

    from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM

    suffix = str(uuid4())[:8]
    full_name = f"sync-org-{suffix}/sync-repo-{suffix}"

    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)

    count_before = (
        await db_session.execute(
            select(func.count())
            .select_from(ExternalRepositoryORM)
            .where(ExternalRepositoryORM.provider == PROVIDER_ID)
            .where(ExternalRepositoryORM.full_name == full_name)
        )
    ).scalar_one()
    assert count_before == 1  # sanity: import created exactly one row

    await _sync(app_with_db, app_client_with_db, repo_id, owner_suffix=suffix)

    count_after = (
        await db_session.execute(
            select(func.count())
            .select_from(ExternalRepositoryORM)
            .where(ExternalRepositoryORM.provider == PROVIDER_ID)
            .where(ExternalRepositoryORM.full_name == full_name)
        )
    ).scalar_one()

    assert count_after == 1  # sync must not add a duplicate row


# ── C ─────────────────────────────────────────────────────────────────────────


async def test_c_repeat_sync_same_content_no_new_versions(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """Re-syncing with identical content must not create a new document version."""
    suffix = str(uuid4())[:8]
    content = "# Version One"
    repo_id = await _import_repo(
        app_with_db, app_client_with_db, owner_suffix=suffix, content=content
    )

    # first sync — same content as import → no new version
    status1, body1 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content
    )
    assert status1 == 200, body1
    assert body1["versions_created"] == 0
    assert body1["versions_skipped"] >= 1

    # second sync — still same content → still no new version
    status2, body2 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content
    )
    assert status2 == 200, body2
    assert body2["versions_created"] == 0
    assert body2["versions_skipped"] >= 1


# ── D ─────────────────────────────────────────────────────────────────────────


async def test_d_sync_changed_content_creates_new_version(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """Syncing with changed content must create exactly one new document version."""
    suffix = str(uuid4())[:8]
    content_a = "# Version One"
    content_b = "# Version Two — changed"

    repo_id = await _import_repo(
        app_with_db, app_client_with_db, owner_suffix=suffix, content=content_a
    )

    # sync with same content — idempotent (version from import already exists)
    s0, b0 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content_a
    )
    assert s0 == 200, b0

    # sync with changed content → new version
    status, body = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content=content_b
    )
    assert status == 200, body
    assert body["versions_created"] == 1


# ── E ─────────────────────────────────────────────────────────────────────────


async def test_e_failed_sync_marks_run_as_failed(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Connector failure → API returns 500, sync_run committed as failed with error_message."""
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)

    status, _ = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, failing=True
    )
    assert status == 500

    # route handler committed mark_failed before raising 500 — verify via DB
    result = await db_session.execute(
        select(RepositorySyncRunORM)
        .where(RepositorySyncRunORM.repository_id == repo_id)
        .where(RepositorySyncRunORM.status == "failed")
        .order_by(RepositorySyncRunORM.created_at.desc(), RepositorySyncRunORM.id.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    assert run is not None, "Expected a failed sync_run in DB after 500 response"
    assert run.error_message is not None
    assert "connector boom" in run.error_message


# ── F ─────────────────────────────────────────────────────────────────────────


async def test_f_list_sync_runs_newest_first(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """GET /sync-runs returns runs newest first, with all required fields."""
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, owner_suffix=suffix)

    # create 2 syncs with different content so we get 2 distinct runs
    sf1, body1 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content="# Run F1"
    )
    assert sf1 == 200, body1
    sf2, body2 = await _sync(
        app_with_db, app_client_with_db, repo_id, owner_suffix=suffix, content="# Run F2 — changed"
    )
    assert sf2 == 200, body2
    sync_run_id1 = body1["sync_run_id"]
    sync_run_id2 = body2["sync_run_id"]

    registry = ConnectorRegistry()
    registry.register(_FakeSyncConnector(owner_suffix=suffix))
    app_with_db.state.connector_registry = registry

    resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/sync-runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 2

    # newest first: body2's run must appear before body1's run
    run_ids = [r["id"] for r in runs]
    assert run_ids.index(sync_run_id2) < run_ids.index(sync_run_id1)

    # required fields present in every item
    first = runs[0]
    for field in (
        "id",
        "repository_id",
        "trigger",
        "mode",
        "status",
        "started_at",
        "finished_at",
        "raw_objects_processed",
        "documents_created",
        "versions_created",
        "versions_skipped",
        "warnings_count",
        "error_message",
    ):
        assert field in first, f"Missing field in sync-run list item: {field}"


# ── G ─────────────────────────────────────────────────────────────────────────


async def test_g_sync_nonexistent_repository_returns_404(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    """POST /sync for an unknown UUID returns 404."""
    registry = ConnectorRegistry()
    registry.register(_FakeSyncConnector())
    app_with_db.state.connector_registry = registry

    resp = await app_client_with_db.post(f"/api/v1/repositories/{uuid4()}/sync")
    assert resp.status_code == 404
