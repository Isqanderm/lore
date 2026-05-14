"""API lifecycle tests for repository_structure artifact — tests A through F."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

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
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

CONNECTOR_ID = "fake-structure"

DEFAULT_PATHS = [
    "README.md",
    "pyproject.toml",
    "apps/api/main.py",
    "lore/ingestion/service.py",
    "tests/unit/test_service.py",
    "docs/index.md",
    ".github/workflows/ci.yml",
    "Dockerfile",
]


class _FakeStructureConnector(BaseConnector):
    def __init__(self, owner_suffix: str, paths: list[str] | None = None) -> None:
        self._suffix = owner_suffix
        self._paths = paths if paths is not None else DEFAULT_PATHS

    @property
    def _owner(self) -> str:
        return f"struct-org-{self._suffix}"

    @property
    def _repo(self) -> str:
        return f"struct-repo-{self._suffix}"

    @property
    def _full_name(self) -> str:
        return f"{self._owner}/{self._repo}"

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id=CONNECTOR_ID,
            display_name="Fake Structure",
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
            provider=CONNECTOR_ID,
            owner=self._owner,
            name=self._repo,
            full_name=self._full_name,
            default_branch="main",
            html_url=f"https://example.com/{self._full_name}",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raw_objects = []
        for path in self._paths:
            payload = {"path": path, "owner": self._owner, "repo": self._repo}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            content = f"# {path}"
            raw = RawExternalObject(
                provider=CONNECTOR_ID,
                object_type="github.file",
                external_id=f"{self._full_name}:file:{path}",
                external_url=f"https://example.com/{self._full_name}/blob/main/{path}",
                connection_id=request.connection_id,
                repository_id=request.repository_id,
                raw_payload=payload,
                raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                content=content,
                content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
                source_updated_at=None,
                fetched_at=datetime.now(UTC),
                metadata={
                    "commit_sha": "abc123",
                    "path": path,
                    "owner": self._owner,
                    "repo": self._repo,
                    "branch": "main",
                },
            )
            raw_objects.append(raw)
        return SyncResult(connector_id=CONNECTOR_ID, raw_objects=raw_objects)

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


async def _import_repo(
    app: FastAPI,
    client: AsyncClient,
    suffix: str,
    paths: list[str] | None = None,
) -> UUID:
    connector = _FakeStructureConnector(owner_suffix=suffix, paths=paths)
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(
        "/api/v1/repositories/import",
        json={
            "url": f"https://example.com/struct-org-{suffix}/struct-repo-{suffix}",
            "connector_id": CONNECTOR_ID,
        },
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()["repository_id"])


async def _sync_repo(
    app: FastAPI,
    client: AsyncClient,
    repo_id: UUID,
    suffix: str,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    connector = _FakeStructureConnector(owner_suffix=suffix, paths=paths)
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(f"/api/v1/repositories/{repo_id}/sync")
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def test_a_get_structure_missing_before_generation(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)

    resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/structure")
    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is False
    assert data["state"] == "missing"
    assert data["reason"] == "structure_not_generated"
    assert data["artifact_type"] == "repository_structure"


async def test_b_generate_structure_after_import(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)

    resp = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")
    assert resp.status_code == 200
    data = resp.json()

    assert data["exists"] is True
    assert data["state"] == "fresh"
    assert data["artifact_type"] == "repository_structure"
    assert data["is_stale"] is False

    structure = data["structure"]
    assert structure["stats"]["total_active_files"] == len(DEFAULT_PATHS)
    assert structure["stats"]["manifest_count"] == 1

    dir_paths = [e["path"] for e in structure["tree"]["top_level_directories"]]
    assert "apps" in dir_paths
    assert "lore" in dir_paths
    assert "tests" in dir_paths
    assert "docs" in dir_paths
    assert ".github" in dir_paths

    manifest_kinds = {m["path"]: m["kind"] for m in structure["manifests"]}
    assert manifest_kinds["pyproject.toml"] == "python.project"

    entrypoint_kinds = {e["path"]: e["kind"] for e in structure["entrypoint_candidates"]}
    assert entrypoint_kinds.get("apps/api/main.py") == "fastapi.app_candidate"

    assert "Dockerfile" in structure["infrastructure"]["docker_files"]
    assert ".github/workflows/ci.yml" in structure["infrastructure"]["ci_files"]

    assert "apps" in structure["classification"]["source_roots"]
    assert "lore" in structure["classification"]["source_roots"]
    assert "tests" in structure["classification"]["test_roots"]
    assert "docs" in structure["classification"]["docs_roots"]
    assert ".github" in structure["classification"]["config_roots"]


async def test_c_get_structure_fresh_after_generation(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)
    await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")

    resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/structure")
    assert resp.status_code == 200
    data = resp.json()

    assert data["exists"] is True
    assert data["state"] == "fresh"
    assert data["is_stale"] is False
    assert data["artifact_type"] == "repository_structure"


async def test_d_structure_becomes_stale_after_new_successful_sync(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)

    gen_resp = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")
    assert gen_resp.status_code == 200
    source_sync_run_id = gen_resp.json()["source_sync_run_id"]

    await _sync_repo(app_with_db, app_client_with_db, repo_id, suffix)

    get_resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/structure")
    assert get_resp.status_code == 200
    data = get_resp.json()

    assert data["state"] == "stale"
    assert data["is_stale"] is True
    assert data["current_sync_run_id"] != source_sync_run_id


async def test_e_structure_uses_only_active_documents(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    paths_sync1 = ["README.md", "apps/api/main.py"]
    paths_sync2 = ["README.md"]

    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix, paths=paths_sync1)

    gen1 = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")
    assert gen1.status_code == 200
    s1 = gen1.json()["structure"]
    entry_paths_1 = [e["path"] for e in s1["entrypoint_candidates"]]
    assert "apps/api/main.py" in entry_paths_1
    assert s1["stats"]["total_active_files"] == 2

    await _sync_repo(app_with_db, app_client_with_db, repo_id, suffix, paths=paths_sync2)

    gen2 = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")
    assert gen2.status_code == 200
    s2 = gen2.json()["structure"]
    entry_paths_2 = [e["path"] for e in s2["entrypoint_candidates"]]
    assert "apps/api/main.py" not in entry_paths_2
    assert s2["stats"]["total_active_files"] == 1


async def test_f_generate_structure_without_succeeded_sync_returns_409(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:6]

    conn = ExternalConnectionORM(
        id=uuid4(),
        provider="github",
        auth_mode="env_pat",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    db_session.add(conn)
    await db_session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(),
        connection_id=conn.id,
        provider="github",
        owner=f"nosync-{suffix}",
        name=f"repo-{suffix}",
        full_name=f"nosync-{suffix}/repo-{suffix}",
        default_branch="main",
        html_url=f"https://example.com/nosync-{suffix}/repo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    db_session.add(repo)
    await db_session.flush()
    await db_session.commit()  # ensure row is visible to the route handler's session

    resp = await app_client_with_db.post(f"/api/v1/repositories/{repo.id}/structure/generate")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "repository_not_synced"
