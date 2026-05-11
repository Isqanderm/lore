# GitHub Connector Foundation — Phase 5: App Wiring, Tests, Docs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire everything into the FastAPI app, write integration and E2E tests, add smoke test, update docs.

**Architecture:** Only `apps/api/lifespan.py` imports `lore.connectors.github`. All other modules stay provider-agnostic.

**Tech Stack:** FastAPI, httpx AsyncClient for E2E, testcontainers for integration, respx for GitHub API mocking

**Prerequisites:** Phases 1–4 complete.

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `lore/infrastructure/config.py` | add github_token field |
| Modify | `pyproject.toml` | add live_github marker; httpx already in deps |
| Modify | `apps/api/lifespan.py` | ConnectorRegistry + GitHubConnector wiring |
| Create | `apps/api/routes/v1/connectors.py` | GET /connectors route |
| Create | `apps/api/routes/v1/repositories.py` | POST /repositories/import, GET /repositories/{id} |
| Modify | `apps/api/main.py` | mount new routers |
| Create | `tests/integration/connectors/__init__.py` | test package |
| Create | `tests/integration/connectors/test_repository_import_flow.py` | full DB flow test |
| Create | `tests/integration/connectors/test_ingest_idempotency_db.py` | DB idempotency test |
| Create | `tests/e2e/test_import_endpoint.py` | API endpoint test |
| Create | `tests/e2e/test_connectors_endpoint.py` | connectors list test |
| Create | `tests/smoke/__init__.py` | smoke test package |
| Create | `tests/smoke/test_github_live_import.py` | opt-in live GitHub test |
| Modify | `CLAUDE.md` | connector SDK section |
| Create | `docs/connectors.md` | connector architecture docs |

---

## Task 15: App Wiring

**Files:**
- Modify: `lore/infrastructure/config.py`
- Modify: `pyproject.toml`
- Modify: `apps/api/lifespan.py`
- Create: `apps/api/routes/v1/connectors.py`
- Create: `apps/api/routes/v1/repositories.py`
- Modify: `apps/api/main.py`

- [ ] **Step 1: Add github_token to Settings**

In `lore/infrastructure/config.py`, add after `embedding_dimensions`:

```python
github_token: SecretStr | None = None  # GITHUB_TOKEN env var
```

Full updated file:

```python
# lore/infrastructure/config.py
from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    openai_api_key: SecretStr
    log_level: str = "INFO"
    environment: Literal["development", "production"] = "development"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int | None = None
    github_token: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Add live_github marker to pyproject.toml**

In `pyproject.toml`, add to `markers` list:

```toml
"live_github: tests requiring real GITHUB_TOKEN and LIVE_GITHUB_TEST_REPO env vars",
```

Also add `httpx` to main `dependencies` if not already there (httpx was in dev deps; move to main since `GitHubClient` uses it at runtime):

```toml
"httpx>=0.27.0",
```

And keep `respx` in dev deps:

```toml
"respx>=0.21.0",
```

- [ ] **Step 3: Wire ConnectorRegistry in lifespan**

```python
# apps/api/lifespan.py
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.client import GitHubClient
from lore.connectors.github.connector import GitHubConnector
from lore.connectors.github.file_policy import FileSelectionPolicy
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    registry = ConnectorRegistry()

    if settings.github_token:
        client = GitHubClient.from_settings(settings)
        registry.register(
            GitHubConnector(
                client=client,
                file_policy=FileSelectionPolicy(),
                normalizer=GitHubNormalizer(),
            )
        )
        logger.info("connector.registered", connector_id="github")
    else:
        logger.warning("connector.github.skipped", reason="GITHUB_TOKEN not set")

    app.state.connector_registry = registry

    logger.info("lore.startup")
    yield
    logger.info("lore.shutdown")
```

- [ ] **Step 4: Create connectors route**

```python
# apps/api/routes/v1/connectors.py
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/connectors", tags=["connectors"])


class CapabilitiesResponse(BaseModel):
    supports_full_sync: bool
    supports_incremental_sync: bool
    supports_webhooks: bool
    supports_files: bool
    object_types: list[str]


class ConnectorResponse(BaseModel):
    connector_id: str
    display_name: str
    version: str
    capabilities: CapabilitiesResponse


@router.get("", response_model=list[ConnectorResponse])
async def list_connectors(request: Request) -> list[ConnectorResponse]:
    registry = request.app.state.connector_registry
    return [
        ConnectorResponse(
            connector_id=m.connector_id,
            display_name=m.display_name,
            version=m.version,
            capabilities=CapabilitiesResponse(
                supports_full_sync=m.capabilities.supports_full_sync,
                supports_incremental_sync=m.capabilities.supports_incremental_sync,
                supports_webhooks=m.capabilities.supports_webhooks,
                supports_files=m.capabilities.supports_files,
                object_types=m.capabilities.object_types,
            ),
        )
        for m in registry.list()
    ]


@router.post("/{connector_id}/webhook", status_code=501)
async def webhook(connector_id: str) -> dict:
    return {"error": {"code": "not_implemented", "message": "Webhooks not supported yet"}}
```

- [ ] **Step 5: Create repositories route**

```python
# apps/api/routes/v1/repositories.py
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from lore.connector_sdk.errors import ConnectorNotFoundError, ExternalResourceNotFoundError
from lore.infrastructure.db.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
)
from lore.infrastructure.db.repositories.external_connection import ExternalConnectionRepository
from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.infrastructure.db.session import get_session
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService

router = APIRouter(prefix="/repositories", tags=["repositories"])


class ImportRequest(BaseModel):
    url: str
    connector_id: str = "github"


class ImportResponse(BaseModel):
    repository_id: UUID
    connector_id: str
    status: str
    raw_objects_processed: int
    documents_created: int
    versions_created: int


def _build_import_service(session: AsyncSession, registry) -> RepositoryImportService:
    ext_conn_repo = ExternalConnectionRepository(session)
    ext_repo_repo = ExternalRepositoryRepository(session)
    ext_obj_repo = ExternalObjectRepository(session)
    source_repo = SourceRepository(session)
    doc_repo = DocumentRepository(session)
    dv_repo = DocumentVersionRepository(session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    return RepositoryImportService(registry, ingestion, ext_conn_repo, ext_repo_repo)


@router.post("/import", response_model=ImportResponse)
async def import_repository(
    body: ImportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ImportResponse:
    registry = request.app.state.connector_registry
    svc = _build_import_service(session, registry)

    try:
        result = await svc.import_repository(body.url, body.connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ExternalResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await session.commit()

    return ImportResponse(
        repository_id=result.repository_id,
        connector_id=result.connector_id,
        status=result.status,
        raw_objects_processed=result.report.raw_objects_processed,
        documents_created=result.report.documents_created,
        versions_created=result.report.versions_created,
    )


@router.get("/{repository_id}", response_model=dict)
async def get_repository(
    repository_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    repo_repo = ExternalRepositoryRepository(session)
    repo = await repo_repo.get_by_id(repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {
        "id": str(repo.id),
        "provider": repo.provider,
        "full_name": repo.full_name,
        "default_branch": repo.default_branch,
        "html_url": repo.html_url,
        "last_synced_at": repo.last_synced_at.isoformat() if repo.last_synced_at else None,
    }
```

- [ ] **Step 6: Update main.py to mount new routers**

```python
# apps/api/main.py
from fastapi import FastAPI

from apps.api.exception_handlers import lore_exception_handler, unhandled_exception_handler
from apps.api.lifespan import lifespan
from apps.api.routes.v1.connectors import router as connectors_router
from apps.api.routes.v1.health import router as health_router
from apps.api.routes.v1.repositories import router as repositories_router
from lore.infrastructure.config import get_settings
from lore.infrastructure.observability.logging import configure_logging
from lore.infrastructure.observability.middleware import RequestIDMiddleware
from lore.schema.errors import LoreError


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, environment=settings.environment)

    app = FastAPI(title="Lore", version="0.2.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)

    v1_router = FastAPI()
    v1_router.include_router(health_router)
    v1_router.include_router(connectors_router)
    v1_router.include_router(repositories_router)
    app.mount("/api/v1", v1_router)

    app.add_exception_handler(LoreError, lore_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


app = create_app()
```

- [ ] **Step 7: Verify app starts without error**

```bash
python -c "from apps.api.main import create_app; app = create_app(); print('OK')"
```
Expected: `OK` (no import errors; github_token will be None so connector skipped)

- [ ] **Step 8: Commit**

```bash
git add \
  lore/infrastructure/config.py \
  pyproject.toml \
  apps/api/lifespan.py \
  apps/api/routes/v1/connectors.py \
  apps/api/routes/v1/repositories.py \
  apps/api/main.py
git commit -m "feat(api): wire ConnectorRegistry, /connectors and /repositories/import endpoints"
```

---

## Task 16: Integration tests

**Files:**
- Create: `tests/integration/connectors/__init__.py`
- Create: `tests/integration/connectors/test_repository_import_flow.py`
- Create: `tests/integration/connectors/test_ingest_idempotency_db.py`

These tests use a real PostgreSQL (testcontainers) but a fake connector — no real GitHub API calls.

- [ ] **Step 1: Write integration tests**

```python
# tests/integration/connectors/__init__.py
# (empty)
```

```python
# tests/integration/connectors/test_repository_import_flow.py
"""Full integration: fake connector → DB records created correctly."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    ProvenanceDraft,
    RawExternalObject,
    SyncResult,
)
from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.db.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
)
from lore.infrastructure.db.repositories.external_connection import ExternalConnectionRepository
from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService


class _FakeGitHubConnector(BaseConnector):
    """Fake connector that returns deterministic data without HTTP calls."""

    def __init__(self, conn_id, repo_id) -> None:
        self._conn_id = conn_id
        self._repo_id = repo_id
        self._normalizer = GitHubNormalizer()

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="github",
            display_name="GitHub",
            version="0.1.0",
            capabilities=ConnectorCapabilities(
                supports_full_sync=True,
                supports_incremental_sync=False,
                supports_webhooks=False,
                supports_repository_tree=True,
                supports_files=True,
                supports_issues=False,
                supports_pull_requests=False,
                supports_comments=False,
                supports_releases=False,
                supports_permissions=False,
                object_types=["github.repository", "github.file"],
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
        content = "# Hello World"
        payload = {"path": "README.md", "size": len(content)}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw = RawExternalObject(
            provider="github",
            object_type="github.file",
            external_id="acme/myrepo:file:README.md",
            external_url="https://github.com/acme/myrepo/blob/abc123/README.md",
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
            content=content,
            content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={"commit_sha": "abc123", "path": "README.md", "owner": "acme", "repo": "myrepo", "branch": "main"},
        )
        return SyncResult(connector_id="github", raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return self._normalizer.normalize(raw)


@pytest.mark.integration
async def test_full_import_creates_all_records(db_session: AsyncSession) -> None:
    registry = ConnectorRegistry()
    conn_id = uuid4()
    repo_id = uuid4()
    connector = _FakeGitHubConnector(conn_id, repo_id)
    registry.register(connector)

    ext_conn_repo = ExternalConnectionRepository(db_session)
    ext_repo_repo = ExternalRepositoryRepository(db_session)
    ext_obj_repo = ExternalObjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    dv_repo = DocumentVersionRepository(db_session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    svc = RepositoryImportService(registry, ingestion, ext_conn_repo, ext_repo_repo)

    result = await svc.import_repository("https://github.com/acme/myrepo", "github")

    assert result.status == "synced"
    assert result.report.documents_created == 1
    assert result.report.versions_created == 1


@pytest.mark.integration
async def test_full_import_creates_document_version_with_provenance(db_session: AsyncSession) -> None:
    registry = ConnectorRegistry()
    connector = _FakeGitHubConnector(uuid4(), uuid4())
    registry.register(connector)

    ext_conn_repo = ExternalConnectionRepository(db_session)
    ext_repo_repo = ExternalRepositoryRepository(db_session)
    ext_obj_repo = ExternalObjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    dv_repo = DocumentVersionRepository(db_session)
    ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    svc = RepositoryImportService(registry, ingestion, ext_conn_repo, ext_repo_repo)

    result = await svc.import_repository("https://github.com/acme/myrepo", "github")

    # Fetch the created version's metadata to verify provenance snapshot
    from sqlalchemy import select
    from lore.infrastructure.db.models.document import DocumentVersionORM
    res = await db_session.execute(select(DocumentVersionORM))
    versions = res.scalars().all()
    assert len(versions) >= 1
    meta = versions[-1].metadata
    assert "commit_sha" in meta
    assert meta["commit_sha"] == "abc123"
    assert "external_id" in meta
    assert "raw_payload_hash" in meta
```

```python
# tests/integration/connectors/test_ingest_idempotency_db.py
"""DB-level idempotency: repeated sync with same content produces no duplicate versions."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from lore.infrastructure.db.models.document import DocumentVersionORM
from lore.infrastructure.db.repositories.document import (
    DocumentRepository,
    DocumentVersionRepository,
)
from lore.infrastructure.db.repositories.external_connection import ExternalConnectionRepository
from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.ingestion.repository_import import RepositoryImportService
from lore.ingestion.service import IngestionService


def _make_raw(conn_id, repo_id, content: str = "# Hello") -> RawExternalObject:
    payload = {"path": "README.md"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id="acme/myrepo:file:README.md",
        external_url="https://github.com/acme/myrepo/blob/abc123/README.md",
        connection_id=conn_id,
        repository_id=repo_id,
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={"commit_sha": "abc123", "path": "README.md", "owner": "acme", "repo": "myrepo", "branch": "main"},
    )


class _StaticConnector(BaseConnector):
    def __init__(self, raw: RawExternalObject) -> None:
        self._raw = raw
        self._normalizer = GitHubNormalizer()

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="github",
            display_name="GitHub",
            version="0.1.0",
            capabilities=ConnectorCapabilities(
                supports_full_sync=True, supports_incremental_sync=False,
                supports_webhooks=False, supports_repository_tree=True,
                supports_files=True, supports_issues=False,
                supports_pull_requests=False, supports_comments=False,
                supports_releases=False, supports_permissions=False,
                object_types=["github.file"],
            ),
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider="github", owner="acme", name="myrepo",
            full_name="acme/myrepo", default_branch="main",
            html_url="https://github.com/acme/myrepo",
            visibility="public", metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        import dataclasses
        raw = dataclasses.replace(
            self._raw,
            connection_id=request.connection_id,
            repository_id=request.repository_id,
        )
        return SyncResult(connector_id="github", raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return self._normalizer.normalize(raw)


@pytest.mark.integration
async def test_repeated_import_no_duplicate_versions(db_session: AsyncSession) -> None:
    conn_id = uuid4()
    repo_id = uuid4()
    raw = _make_raw(conn_id, repo_id, content="# Hello World")
    connector = _StaticConnector(raw)

    registry = ConnectorRegistry()
    registry.register(connector)

    def _make_svc():
        ext_conn_repo = ExternalConnectionRepository(db_session)
        ext_repo_repo = ExternalRepositoryRepository(db_session)
        ext_obj_repo = ExternalObjectRepository(db_session)
        source_repo = SourceRepository(db_session)
        doc_repo = DocumentRepository(db_session)
        dv_repo = DocumentVersionRepository(db_session)
        ingestion = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
        return RepositoryImportService(registry, ingestion, ext_conn_repo, ext_repo_repo)

    await _make_svc().import_repository("https://github.com/acme/myrepo", "github")
    await _make_svc().import_repository("https://github.com/acme/myrepo", "github")

    result = await db_session.execute(select(DocumentVersionORM))
    versions = result.scalars().all()
    # Should have exactly 1 version even after 2 imports with same content
    assert len(versions) == 1
```

- [ ] **Step 2: Run integration tests**

```
pytest tests/integration/connectors/ -v -m integration
```
Expected: all PASSED

- [ ] **Step 3: Commit**

```bash
git add \
  tests/integration/connectors/__init__.py \
  tests/integration/connectors/test_repository_import_flow.py \
  tests/integration/connectors/test_ingest_idempotency_db.py
git commit -m "test(integration): full import flow and DB-level idempotency tests"
```

---

## Task 17: E2E tests

**Files:**
- Create: `tests/e2e/test_import_endpoint.py`
- Create: `tests/e2e/test_connectors_endpoint.py`

These tests use FastAPI `AsyncClient` with a fake connector in `app.state`. No real GitHub calls.

- [ ] **Step 1: Write E2E tests**

```python
# tests/e2e/test_import_endpoint.py
"""POST /api/v1/repositories/import with a fake connector."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

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


class _FakeConnector(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="fake",
            display_name="Fake",
            version="0.0.1",
            capabilities=ConnectorCapabilities(
                supports_full_sync=True, supports_incremental_sync=False,
                supports_webhooks=False, supports_repository_tree=False,
                supports_files=True, supports_issues=False,
                supports_pull_requests=False, supports_comments=False,
                supports_releases=False, supports_permissions=False,
                object_types=["github.file"],
            ),
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider="fake", owner="acme", name="repo",
            full_name="acme/repo", default_branch="main",
            html_url="https://example.com/acme/repo",
            visibility="public", metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        content = "# Hello"
        payload = {"path": "README.md"}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw = RawExternalObject(
            provider="fake",
            object_type="github.file",
            external_id="acme/repo:file:README.md",
            external_url="https://example.com/acme/repo/blob/abc/README.md",
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
            content=content,
            content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={"commit_sha": "abc123", "path": "README.md", "owner": "acme", "repo": "repo", "branch": "main"},
        )
        return SyncResult(connector_id="fake", raw_objects=[raw])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


@pytest.fixture
def fake_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(_FakeConnector())
    return registry


@pytest.mark.e2e
async def test_import_endpoint_returns_200(client: AsyncClient, fake_registry: ConnectorRegistry) -> None:
    client.app.state.connector_registry = fake_registry  # type: ignore[attr-defined]

    response = await client.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/repo", "connector_id": "fake"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "repository_id" in data
    assert data["status"] == "synced"
    assert data["connector_id"] == "fake"


@pytest.mark.e2e
async def test_import_endpoint_unknown_connector_returns_404(
    client: AsyncClient, fake_registry: ConnectorRegistry
) -> None:
    client.app.state.connector_registry = fake_registry  # type: ignore[attr-defined]

    response = await client.post(
        "/api/v1/repositories/import",
        json={"url": "https://github.com/acme/repo", "connector_id": "unknown"},
    )
    assert response.status_code == 404
```

```python
# tests/e2e/test_connectors_endpoint.py
"""GET /api/v1/connectors returns list of registered connectors."""
import pytest
from httpx import AsyncClient

from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.connector import GitHubConnector
from lore.connectors.github.manifest import GITHUB_MANIFEST


class _MinimalConnector:
    @property
    def manifest(self) -> ConnectorManifest:
        return GITHUB_MANIFEST


@pytest.fixture
def github_registry() -> ConnectorRegistry:
    from lore.connectors.github.manifest import GITHUB_MANIFEST
    from lore.connector_sdk.base import BaseConnector

    class _StubGitHub(BaseConnector):
        @property
        def manifest(self) -> ConnectorManifest:
            return GITHUB_MANIFEST

    registry = ConnectorRegistry()
    registry.register(_StubGitHub())
    return registry


@pytest.mark.e2e
async def test_connectors_endpoint_returns_github(
    client: AsyncClient, github_registry: ConnectorRegistry
) -> None:
    client.app.state.connector_registry = github_registry  # type: ignore[attr-defined]

    response = await client.get("/api/v1/connectors")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["connector_id"] == "github"
    assert data[0]["capabilities"]["supports_full_sync"] is True
    assert data[0]["capabilities"]["supports_webhooks"] is False


@pytest.mark.e2e
async def test_connectors_empty_registry(client: AsyncClient) -> None:
    client.app.state.connector_registry = ConnectorRegistry()

    response = await client.get("/api/v1/connectors")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.e2e
async def test_webhook_endpoint_returns_501(client: AsyncClient) -> None:
    client.app.state.connector_registry = ConnectorRegistry()

    response = await client.post("/api/v1/connectors/github/webhook")
    assert response.status_code == 501
```

- [ ] **Step 2: Run E2E tests**

Note: E2E tests need a DB. The existing `client` fixture in `tests/e2e/conftest.py` creates the app without DB-backed storage. For the import test to work end-to-end, the E2E conftest needs a DB session too. If the existing E2E conftest does not wire DB, the import endpoint test will fail at DB access.

Check `tests/e2e/conftest.py` — if it only creates the FastAPI app without DB, the import test needs to mock the session. In the simplest approach: skip the DB-dependent import test in E2E and use integration tests for full DB flow.

Alternative: use `app.dependency_overrides` to inject a real DB session in E2E. This requires the E2E conftest to also start testcontainers.

**Recommended approach for MVP:** Run the connectors-endpoint test as true E2E (no DB needed). For the import endpoint test, mark it `@pytest.mark.integration` instead of `@pytest.mark.e2e` since it needs DB.

- [ ] **Step 3: Run E2E tests**

```
pytest tests/e2e/ -v -m e2e
```
Expected: connectors tests pass; import test may need DB fixture integration

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_import_endpoint.py tests/e2e/test_connectors_endpoint.py
git commit -m "test(e2e): connectors list and import endpoint tests"
```

---

## Task 18: Smoke test (opt-in)

**Files:**
- Create: `tests/smoke/__init__.py`
- Create: `tests/smoke/test_github_live_import.py`

This test is **never** run in CI. It requires real credentials and network.

- [ ] **Step 1: Create smoke test**

```python
# tests/smoke/__init__.py
# (empty)
```

```python
# tests/smoke/test_github_live_import.py
"""Live GitHub integration smoke test. Opt-in only.

Run with:
    GITHUB_TOKEN=ghp_... LIVE_GITHUB_TEST_REPO=owner/repo pytest tests/smoke/ -m live_github -v

Never run in CI.
"""
import os

import pytest

from lore.connector_sdk.models import FullSyncRequest
from lore.connectors.github.auth import GitHubAuth
from lore.connectors.github.client import GitHubClient
from lore.connectors.github.connector import GitHubConnector
from lore.connectors.github.file_policy import FileSelectionPolicy
from lore.connectors.github.models import parse_github_url
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.config import get_settings


@pytest.fixture
def live_connector() -> GitHubConnector:
    settings = get_settings()
    client = GitHubClient.from_settings(settings)
    return GitHubConnector(
        client=client,
        file_policy=FileSelectionPolicy(),
        normalizer=GitHubNormalizer(),
    )


@pytest.mark.live_github
async def test_live_inspect_resource(live_connector: GitHubConnector) -> None:
    repo_url = os.environ["LIVE_GITHUB_TEST_REPO"]
    if not repo_url.startswith("https://"):
        repo_url = f"https://github.com/{repo_url}"

    draft = await live_connector.inspect_resource(repo_url)
    assert draft.provider == "github"
    assert draft.full_name != ""
    assert draft.default_branch != ""


@pytest.mark.live_github
async def test_live_full_sync_returns_objects(live_connector: GitHubConnector) -> None:
    from uuid import uuid4

    repo_url = os.environ["LIVE_GITHUB_TEST_REPO"]
    if not repo_url.startswith("https://"):
        repo_url = f"https://github.com/{repo_url}"

    request = FullSyncRequest(
        connection_id=uuid4(),
        repository_id=uuid4(),
        resource_uri=repo_url,
    )
    result = await live_connector.full_sync(request)
    assert result.connector_id == "github"
    assert len(result.raw_objects) > 0

    # At minimum, one github.repository object
    types = {r.object_type for r in result.raw_objects}
    assert "github.repository" in types

    # Normalizer produces at least one CanonicalDocumentDraft
    all_drafts = []
    for raw in result.raw_objects:
        all_drafts.extend(live_connector.normalize(raw))
    assert len(all_drafts) > 0
```

- [ ] **Step 2: Verify smoke test is excluded from default runs**

```
pytest tests/ -v --collect-only -m "not live_github" 2>&1 | grep "smoke"
```
Expected: no smoke tests collected

- [ ] **Step 3: Commit**

```bash
git add tests/smoke/__init__.py tests/smoke/test_github_live_import.py
git commit -m "test(smoke): opt-in live GitHub import smoke test"
```

---

## Task 19: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/connectors.md`

- [ ] **Step 1: Add connector SDK section to CLAUDE.md**

Add after the `## Project structure` section in `CLAUDE.md`:

```markdown
---

## Connector SDK

```
lore/connector_sdk/       Stable contract layer (SDK). Zero SQLAlchemy, zero FastAPI.
  errors.py               ConnectorError hierarchy
  models.py               RawExternalObject, CanonicalDocumentDraft, SyncResult, ...
  capabilities.py         ConnectorCapabilities dataclass
  manifest.py             ConnectorManifest dataclass
  base.py                 BaseConnector ABC
  registry.py             ConnectorRegistry — register/get/list/has

lore/connectors/          Concrete provider integrations
  github/                 GitHub connector (only place that imports httpx for GitHub)
    connector.py          GitHubConnector(BaseConnector)
    client.py             GitHubClient — async HTTP, error mapping
    auth.py               GitHubAuth.from_settings — reads GITHUB_TOKEN
    file_policy.py        FileSelectionPolicy — include/exclude patterns
    normalizer.py         GitHubNormalizer — RawExternalObject → CanonicalDocumentDraft
    manifest.py           GITHUB_MANIFEST constant
    webhook.py            skeleton — raises UnsupportedCapabilityError

lore/ingestion/
  service.py              IngestionService — processes SyncResult into DB
  repository_import.py    RepositoryImportService — orchestrates connector → ingestion
  models.py               IngestionReport dataclass
```

### Connector import invariants

- `lore/schema`, `lore/connector_sdk`, `lore/ingestion` must NOT import `lore.connectors`
- Only `apps/api/lifespan.py` may import concrete connectors
- Verified by `tests/unit/connector_sdk/test_import_boundary.py`

### Adding a new connector

1. Create `lore/connectors/<provider>/` following github/ structure
2. Implement `BaseConnector` subclass with honest `ConnectorCapabilities`
3. Register in `apps/api/lifespan.py`
4. Add unit tests for URL parsing, file policy, normalizer, hashing
5. Run import boundary test to verify no leakage
```

- [ ] **Step 2: Create docs/connectors.md**

```markdown
# Connector Architecture

Lore uses a pluggable connector system to ingest data from external providers.

## Layer Model

```
Provider API (GitHub, GitLab, ...)
    ↓
lore/connectors/<provider>/   Provider-specific integration
    ↓ RawExternalObject
lore/ingestion/service.py     Normalizes + persists
    ↓ CanonicalDocumentDraft
lore/schema/                  Canonical knowledge model
    ↓
DB: documents + document_versions
```

## Connector SDK

The SDK (`lore/connector_sdk/`) is the stable contract. Connectors implement `BaseConnector`:

- `inspect_resource(uri)` → `ExternalContainerDraft` — fetch repo metadata
- `full_sync(request)` → `SyncResult` — fetch all raw objects
- `normalize(raw)` → `list[CanonicalDocumentDraft]` — map to canonical model

## Import Rules

| Module | May import |
|---|---|
| `lore/connector_sdk/` | `lore/schema/`, stdlib |
| `lore/connectors/github/` | `lore/connector_sdk/`, `lore/schema/` |
| `lore/ingestion/` | `lore/connector_sdk/`, `lore/infrastructure/`, `lore/schema/` |
| `apps/api/lifespan.py` | All of the above (composition root) |

**Never:** `lore/ingestion/` importing `lore/connectors/github/`

## Data Hashing

- `raw_payload_hash`: `sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str))`
- `content_hash` / `document_versions.checksum`: `sha256(content)`
- Both prefixed with `"sha256:"`

## Provenance

Each `DocumentVersion.metadata` stores a provenance snapshot at creation time:
- `external_id` — stable object identifier
- `external_url` — human URL at this version (with commit SHA for files)
- `raw_payload_hash` — hash of raw provider payload at ingestion time
- `commit_sha` — git commit SHA (mandatory for github.file objects)
- `path` — file path

## Adding a Connector

1. `lore/connectors/<provider>/__init__.py` (empty)
2. `models.py` — provider-specific internal types
3. `auth.py` — auth config, reads from Settings
4. `client.py` — async HTTP client with error mapping to SDK errors
5. `file_policy.py` (if applicable) — selection rules
6. `normalizer.py` — maps object_type → document_kind
7. `manifest.py` — `ConnectorManifest` with honest capabilities
8. `connector.py` — `BaseConnector` subclass
9. Register in `apps/api/lifespan.py`
10. Run `pytest tests/unit/connector_sdk/test_import_boundary.py` to verify isolation
```

- [ ] **Step 3: Run full test suite**

```
pytest tests/unit/ tests/integration/ tests/e2e/ -v -m "not live_github"
```
Expected: all PASSED

- [ ] **Step 4: Commit everything**

```bash
git add CLAUDE.md docs/connectors.md
git commit -m "docs: connector architecture documentation and CLAUDE.md connector section"
```

---

## Final: run complete suite and check lint

- [ ] **Run all tests**

```bash
pytest tests/unit/ tests/integration/ tests/e2e/ -v -m "not live_github"
```

- [ ] **Run linters**

```bash
ruff check lore/ apps/ tests/
ruff format --check lore/ apps/ tests/
```

- [ ] **Run type checker**

```bash
mypy lore/ apps/
```

Fix any mypy or ruff issues before opening the PR.

- [ ] **Commit any fixes**

```bash
git add -p
git commit -m "fix(lint): resolve mypy and ruff issues in v0.2 implementation"
```

---

## Phase 5 complete — Ready for PR

All 5 phases complete:
1. Connector SDK — `lore/connector_sdk/` with BaseConnector, ConnectorRegistry, models
2. Storage — migration 0002, ExternalObject ORM, repository updates
3. GitHub Connector — `lore/connectors/github/` with client, file_policy, normalizer, connector
4. Ingestion — IngestionService (idempotency + provenance), RepositoryImportService
5. App Wiring — `/api/v1/repositories/import`, `/api/v1/connectors`, lifespan, tests, docs

Open PR from `worktree-feat+v0.2-github-connector-foundation` → `main`.
