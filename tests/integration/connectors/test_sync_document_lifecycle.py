"""
Document active-state lifecycle tests via the sync HTTP API.

Each test uses a unique owner_suffix (uuid4 slice) to avoid shared state.
MutableFakeConnector uses connector_id="github" to match repository provider.
external_id is derived from owner/repo/path — stable across syncs for the same path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
from lore.infrastructure.db.models.document import DocumentORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.source import SourceORM

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

LIFECYCLE_PROVIDER = "github"


@dataclass
class _FileConfig:
    path: str
    content: str


class MutableFakeConnector(BaseConnector):
    """Fake connector with mutable file list for lifecycle tests.

    connector_id must be "github" so it matches the repository provider stored at import.
    external_id = "{owner}/{repo}:file:{path}" — stable across syncs for the same path.
    Only content/content_hash change when testing new versions.
    """

    def __init__(self, owner_suffix: str) -> None:
        self._suffix = owner_suffix
        self.files: list[_FileConfig] = []
        self.warnings: list[str] = []
        self._raise_on_sync: Exception | None = None

    @property
    def _owner(self) -> str:
        return f"lc-org-{self._suffix}"

    @property
    def _repo(self) -> str:
        return f"lc-repo-{self._suffix}"

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id=LIFECYCLE_PROVIDER,
            display_name="Lifecycle Fake",
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
            provider=LIFECYCLE_PROVIDER,
            owner=self._owner,
            name=self._repo,
            full_name=f"{self._owner}/{self._repo}",
            default_branch="main",
            html_url=f"https://example.com/{self._owner}/{self._repo}",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        if self._raise_on_sync is not None:
            raise self._raise_on_sync

        raw_objects = []
        for fc in self.files:
            payload = {"path": fc.path, "owner": self._owner, "repo": self._repo}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            raw = RawExternalObject(
                provider=LIFECYCLE_PROVIDER,
                object_type="github.file",
                external_id=f"{self._owner}/{self._repo}:file:{fc.path}",
                external_url=f"https://example.com/{self._owner}/{self._repo}/blob/abc/{fc.path}",
                connection_id=request.connection_id,
                repository_id=request.repository_id,
                raw_payload=payload,
                raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                content=fc.content,
                content_hash="sha256:" + hashlib.sha256(fc.content.encode()).hexdigest(),
                source_updated_at=None,
                fetched_at=datetime.now(UTC),
                metadata={
                    "commit_sha": "abc123",
                    "path": fc.path,
                    "owner": self._owner,
                    "repo": self._repo,
                    "branch": "main",
                },
            )
            raw_objects.append(raw)

        return SyncResult(
            connector_id=LIFECYCLE_PROVIDER,
            raw_objects=raw_objects,
            warnings=list(self.warnings),
        )

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _import_repo(app: FastAPI, client: AsyncClient, connector: MutableFakeConnector) -> UUID:
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    url = f"https://example.com/{connector._owner}/{connector._repo}"
    resp = await client.post(
        "/api/v1/repositories/import",
        json={"url": url, "connector_id": LIFECYCLE_PROVIDER},
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()["repository_id"])


async def _sync(
    app: FastAPI, client: AsyncClient, repo_id: UUID, connector: MutableFakeConnector
) -> tuple[int, dict[str, Any]]:
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(f"/api/v1/repositories/{repo_id}/sync")
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


async def _get_doc(session: AsyncSession, repo_id: UUID, path: str) -> DocumentORM | None:
    result = await session.execute(
        select(DocumentORM)
        .join(SourceORM, DocumentORM.source_id == SourceORM.id)
        .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
        .where(ExternalObjectORM.repository_id == repo_id)
        .where(DocumentORM.path == path)
    )
    return result.scalar_one_or_none()


# ── G: deleted file → inactive after succeeded sync ──────────────────────────


async def test_g_deleted_file_becomes_inactive(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("README.md", "# Hello"), _FileConfig("src/app.py", "code")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    # sync_1 — both files present
    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1
    assert b1["status"] == "succeeded"

    # sync_2 — app.py removed
    connector.files = [_FileConfig("README.md", "# Hello")]
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200, b2
    assert b2["status"] == "succeeded"

    db_session.expire_all()
    readme = await _get_doc(db_session, repo_id, "README.md")
    app_py = await _get_doc(db_session, repo_id, "src/app.py")

    assert readme is not None and readme.is_active is True
    assert app_py is not None
    assert app_py.is_active is False
    assert app_py.deleted_at is not None


# ── H: failed sync does not mark files inactive ───────────────────────────────


async def test_h_failed_sync_does_not_mark_inactive(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("README.md", "# Hello"), _FileConfig("src/app.py", "code")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1

    # sync_2 — connector raises
    connector._raise_on_sync = RuntimeError("network failure")
    s2, _ = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 500

    db_session.expire_all()
    readme = await _get_doc(db_session, repo_id, "README.md")
    app_py = await _get_doc(db_session, repo_id, "src/app.py")

    assert readme is not None and readme.is_active is True
    assert app_py is not None and app_py.is_active is True


# ── I: partial sync does not mark files inactive ──────────────────────────────


async def test_i_partial_sync_does_not_mark_inactive(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("README.md", "# Hello"), _FileConfig("src/app.py", "code")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1

    # sync_2 — returns only README + a warning → partial
    connector.files = [_FileConfig("README.md", "# Hello")]
    connector.warnings = ["rate limit hit — some files skipped"]
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200, b2
    assert b2["status"] == "partial"

    db_session.expire_all()
    app_py = await _get_doc(db_session, repo_id, "src/app.py")

    assert app_py is not None and app_py.is_active is True


# ── J: reappeared file becomes active again ───────────────────────────────────


async def test_j_reappeared_file_becomes_active(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)

    connector.files = [_FileConfig("src/app.py", "code v1")]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200, b1

    # sync_2 — app.py gone → inactive
    connector.files = []
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200 and b2["status"] == "succeeded"

    db_session.expire_all()
    app_py_after_sync2 = await _get_doc(db_session, repo_id, "src/app.py")
    assert app_py_after_sync2 is not None and app_py_after_sync2.is_active is False

    # sync_3 — app.py reappears
    connector.files = [_FileConfig("src/app.py", "code v1")]
    s3, b3 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s3 == 200 and b3["status"] == "succeeded"
    sync_run_3_id = UUID(b3["sync_run_id"])

    db_session.expire_all()
    app_py_after_sync3 = await _get_doc(db_session, repo_id, "src/app.py")
    assert app_py_after_sync3 is not None
    assert app_py_after_sync3.is_active is True
    assert app_py_after_sync3.deleted_at is None
    assert app_py_after_sync3.last_seen_sync_run_id == sync_run_3_id


# ── K: unchanged file still updates last_seen_sync_run_id ────────────────────


async def test_k_unchanged_file_updates_last_seen(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    suffix = str(uuid4())[:8]
    connector = MutableFakeConnector(owner_suffix=suffix)
    content = "# Stable Content"

    connector.files = [_FileConfig("README.md", content)]
    repo_id = await _import_repo(app_with_db, app_client_with_db, connector)

    s1, b1 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s1 == 200 and b1["status"] == "succeeded"

    # sync_2 — same content, no new DocumentVersion
    s2, b2 = await _sync(app_with_db, app_client_with_db, repo_id, connector)
    assert s2 == 200 and b2["status"] == "succeeded"
    assert b2["versions_created"] == 0
    assert b2["versions_skipped"] >= 1
    sync_run_2_id = UUID(b2["sync_run_id"])

    db_session.expire_all()
    readme = await _get_doc(db_session, repo_id, "README.md")
    assert readme is not None
    assert readme.last_seen_sync_run_id == sync_run_2_id
    assert readme.is_active is True
