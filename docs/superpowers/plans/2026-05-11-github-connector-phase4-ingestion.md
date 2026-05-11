# GitHub Connector Foundation — Phase 4: Ingestion Service

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `IngestionService` (processes `SyncResult` into DB) and `RepositoryImportService` (orchestrates connector → ingestion flow). Both depend only on `BaseConnector` — never on concrete connectors.

**Architecture:** IngestionService injects all repositories. RepositoryImportService takes ConnectorRegistry and delegates to IngestionService. Neither imports `lore.connectors.github` directly.

**Tech Stack:** Python 3.12 async, SQLAlchemy async sessions, Pydantic dataclasses

**Prerequisites:** Phase 1 (SDK), Phase 2 (Storage) complete.

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Create | `lore/ingestion/models.py` | IngestionReport dataclass |
| Modify | `lore/ingestion/service.py` | implement IngestionService |
| Create | `lore/ingestion/repository_import.py` | RepositoryImportService |
| Create | `tests/unit/ingestion/__init__.py` | test package |
| Create | `tests/unit/ingestion/test_ingest_idempotency.py` | same content → no new version |
| Create | `tests/unit/ingestion/test_ingest_new_version.py` | changed content → new version |
| Create | `tests/unit/ingestion/test_provenance_preserved.py` | metadata provenance snapshot |

---

## Task 13: IngestionReport + IngestionService

**Files:**
- Create: `lore/ingestion/models.py`
- Modify: `lore/ingestion/service.py`

- [ ] **Step 1: Write ingestion unit tests (they use fake repositories)**

```python
# tests/unit/ingestion/__init__.py
# (empty)
```

```python
# tests/unit/ingestion/test_ingest_idempotency.py
"""Same content_hash on re-sync must NOT create a duplicate DocumentVersion."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ProvenanceDraft,
    RawExternalObject,
    SyncResult,
)
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.ingestion.service import IngestionService
from tests.unit.ingestion._fakes import (
    FakeExternalObjectRepository,
    FakeSourceRepository,
    FakeDocumentRepository,
    FakeDocumentVersionRepository,
    FakeStubConnector,
)


def _raw_file(path: str, content: str, conn_id: UUID, repo_id: UUID) -> RawExternalObject:
    payload = {"path": path}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/abc/{path}",
        connection_id=conn_id,
        repository_id=repo_id,
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={"commit_sha": "abc123", "path": path, "owner": "owner", "repo": "repo", "branch": "main"},
    )


async def test_same_content_no_duplicate_version() -> None:
    conn_id = uuid4()
    repo_id = uuid4()
    raw = _raw_file("README.md", "# Hello", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    ext_obj_repo = FakeExternalObjectRepository()
    source_repo = FakeSourceRepository()
    doc_repo = FakeDocumentRepository()
    dv_repo = FakeDocumentVersionRepository()
    connector = FakeStubConnector(normalizer=GitHubNormalizer())

    svc = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)

    report1 = await svc.ingest_sync_result(sync_result, connector)
    report2 = await svc.ingest_sync_result(sync_result, connector)

    assert report1.documents_created == 1
    assert report1.versions_created == 1
    assert report2.documents_created == 0  # document already exists
    assert report2.versions_created == 0  # same checksum — skipped
    assert len(dv_repo.versions) == 1  # only one version in DB
```

```python
# tests/unit/ingestion/test_ingest_new_version.py
"""Changed content must create a new DocumentVersion."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from lore.connector_sdk.models import RawExternalObject, SyncResult
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.ingestion.service import IngestionService
from tests.unit.ingestion._fakes import (
    FakeExternalObjectRepository,
    FakeSourceRepository,
    FakeDocumentRepository,
    FakeDocumentVersionRepository,
    FakeStubConnector,
)


def _raw_file(path: str, content: str, conn_id, repo_id) -> RawExternalObject:
    payload = {"path": path}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/abc/{path}",
        connection_id=conn_id,
        repository_id=repo_id,
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={"commit_sha": "abc123", "path": path, "owner": "owner", "repo": "repo", "branch": "main"},
    )


async def test_changed_content_creates_new_version() -> None:
    conn_id = uuid4()
    repo_id = uuid4()

    raw_v1 = _raw_file("README.md", "# v1", conn_id, repo_id)
    raw_v2 = _raw_file("README.md", "# v2", conn_id, repo_id)

    ext_obj_repo = FakeExternalObjectRepository()
    source_repo = FakeSourceRepository()
    doc_repo = FakeDocumentRepository()
    dv_repo = FakeDocumentVersionRepository()
    connector = FakeStubConnector(normalizer=GitHubNormalizer())

    svc = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)

    r1 = await svc.ingest_sync_result(SyncResult("stub", [raw_v1]), connector)
    r2 = await svc.ingest_sync_result(SyncResult("stub", [raw_v2]), connector)

    assert r1.versions_created == 1
    assert r2.versions_created == 1
    assert len(dv_repo.versions) == 2
    versions = sorted(dv_repo.versions, key=lambda v: v.version)
    assert versions[0].version == 1
    assert versions[1].version == 2
```

```python
# tests/unit/ingestion/test_provenance_preserved.py
"""DocumentVersion.metadata must contain provenance snapshot."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from lore.connector_sdk.models import RawExternalObject, SyncResult
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.ingestion.service import IngestionService
from tests.unit.ingestion._fakes import (
    FakeExternalObjectRepository,
    FakeSourceRepository,
    FakeDocumentRepository,
    FakeDocumentVersionRepository,
    FakeStubConnector,
)


async def test_version_metadata_contains_provenance_snapshot() -> None:
    conn_id = uuid4()
    repo_id = uuid4()
    content = "# Architecture"
    path = "docs/architecture.md"
    payload = {"path": path}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    raw = RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/deadbeef/{path}",
        connection_id=conn_id,
        repository_id=repo_id,
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={
            "commit_sha": "deadbeef",
            "path": path,
            "owner": "owner",
            "repo": "repo",
            "branch": "main",
        },
    )

    ext_obj_repo = FakeExternalObjectRepository()
    source_repo = FakeSourceRepository()
    doc_repo = FakeDocumentRepository()
    dv_repo = FakeDocumentVersionRepository()
    connector = FakeStubConnector(normalizer=GitHubNormalizer())

    svc = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    await svc.ingest_sync_result(SyncResult("stub", [raw]), connector)

    assert len(dv_repo.versions) == 1
    version_meta = dv_repo.versions[0].metadata

    assert version_meta["external_id"] == f"owner/repo:file:{path}"
    assert version_meta["external_url"] == f"https://github.com/owner/repo/blob/deadbeef/{path}"
    assert "raw_payload_hash" in version_meta
    assert version_meta["commit_sha"] == "deadbeef"
    assert version_meta["path"] == path
```

- [ ] **Step 2: Create fake repositories for unit tests**

```python
# tests/unit/ingestion/_fakes.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import CanonicalDocumentDraft, RawExternalObject
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.db.repositories.external_object import ExternalObject
from lore.schema.document import Document, DocumentVersion
from lore.schema.source import Source, SourceType


@dataclass
class FakeExternalObject:
    id: UUID
    connection_id: UUID
    provider: str
    object_type: str
    external_id: str
    external_url: str | None
    raw_payload_hash: str
    content: str | None
    content_hash: str | None
    repository_id: UUID | None
    source_updated_at: None
    fetched_at: datetime
    raw_payload_json: dict
    metadata: dict


class FakeExternalObjectRepository:
    def __init__(self) -> None:
        self._by_key: dict[tuple[UUID, str, str], FakeExternalObject] = {}

    async def upsert(self, raw: RawExternalObject) -> FakeExternalObject:
        key = (raw.connection_id, raw.provider, raw.external_id)
        obj = FakeExternalObject(
            id=uuid4(),
            connection_id=raw.connection_id,
            provider=raw.provider,
            object_type=raw.object_type,
            external_id=raw.external_id,
            external_url=raw.external_url,
            raw_payload_hash=raw.raw_payload_hash,
            content=raw.content,
            content_hash=raw.content_hash,
            repository_id=raw.repository_id,
            source_updated_at=None,
            fetched_at=raw.fetched_at,
            raw_payload_json=raw.raw_payload,
            metadata=raw.metadata,
        )
        if key in self._by_key:
            obj = FakeExternalObject(**{**obj.__dict__, "id": self._by_key[key].id})
        self._by_key[key] = obj
        return obj


class FakeSourceRepository:
    def __init__(self) -> None:
        self.sources: list[Source] = []

    async def get_by_external_object_id(self, external_object_id: UUID) -> Source | None:
        return next((s for s in self.sources if s.external_object_id == external_object_id), None)

    async def create_with_external_object(
        self, source: Source, external_object_id: UUID
    ) -> Source:
        s = Source(
            id=source.id,
            source_type_raw=source.source_type_raw,
            source_type_canonical=source.source_type_canonical,
            origin=source.origin,
            created_at=source.created_at,
            updated_at=source.updated_at,
            external_object_id=external_object_id,
        )
        self.sources.append(s)
        return s


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.documents: list[Document] = []

    async def get_by_source_kind_path(
        self, source_id: UUID, document_kind: str, logical_path: str
    ) -> Document | None:
        return next(
            (
                d
                for d in self.documents
                if d.source_id == source_id
                and d.document_kind == document_kind
                and d.logical_path == logical_path
            ),
            None,
        )

    async def create(self, doc: Document) -> Document:
        self.documents.append(doc)
        return doc


class FakeDocumentVersionRepository:
    def __init__(self) -> None:
        self.versions: list[DocumentVersion] = []

    async def get_latest_version(self, document_id: UUID) -> DocumentVersion | None:
        doc_versions = [v for v in self.versions if v.document_id == document_id]
        if not doc_versions:
            return None
        return max(doc_versions, key=lambda v: v.version)

    async def get_max_version(self, document_id: UUID) -> int:
        doc_versions = [v for v in self.versions if v.document_id == document_id]
        return max((v.version for v in doc_versions), default=0)

    async def create(self, dv: DocumentVersion) -> DocumentVersion:
        self.versions.append(dv)
        return dv


class FakeStubConnector(BaseConnector):
    def __init__(self, normalizer: GitHubNormalizer) -> None:
        self._normalizer = normalizer

    @property
    def manifest(self) -> ConnectorManifest:
        from lore.connector_sdk.capabilities import ConnectorCapabilities
        return ConnectorManifest(
            connector_id="stub",
            display_name="Stub",
            version="0.0.1",
            capabilities=ConnectorCapabilities(
                supports_full_sync=False,
                supports_incremental_sync=False,
                supports_webhooks=False,
                supports_repository_tree=False,
                supports_files=False,
                supports_issues=False,
                supports_pull_requests=False,
                supports_comments=False,
                supports_releases=False,
                supports_permissions=False,
                object_types=[],
            ),
        )

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return self._normalizer.normalize(raw)
```

- [ ] **Step 3: Run tests to confirm failure**

```
pytest tests/unit/ingestion/ -v
```
Expected: `ModuleNotFoundError` or import errors for `IngestionService`

- [ ] **Step 4: Implement lore/ingestion/models.py**

```python
# lore/ingestion/models.py
from dataclasses import dataclass, field


@dataclass
class IngestionReport:
    raw_objects_processed: int = 0
    documents_created: int = 0
    versions_created: int = 0
    versions_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 5: Implement lore/ingestion/service.py**

```python
# lore/ingestion/service.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.models import CanonicalDocumentDraft, RawExternalObject, SyncResult
from lore.ingestion.models import IngestionReport
from lore.schema.document import Document, DocumentVersion
from lore.schema.source import Source, SourceType

if TYPE_CHECKING:
    from lore.infrastructure.db.repositories.document import (
        DocumentRepository,
        DocumentVersionRepository,
    )
    from lore.infrastructure.db.repositories.external_object import ExternalObjectRepository
    from lore.infrastructure.db.repositories.source import SourceRepository


class IngestionService:
    def __init__(
        self,
        external_object_repo: ExternalObjectRepository,
        source_repo: SourceRepository,
        document_repo: DocumentRepository,
        document_version_repo: DocumentVersionRepository,
    ) -> None:
        self._ext_obj_repo = external_object_repo
        self._source_repo = source_repo
        self._doc_repo = document_repo
        self._dv_repo = document_version_repo

    async def ingest_sync_result(
        self,
        sync_result: SyncResult,
        connector: BaseConnector,
    ) -> IngestionReport:
        report = IngestionReport()
        for raw in sync_result.raw_objects:
            report.raw_objects_processed += 1
            persisted = await self._upsert_raw_object(raw)
            drafts = connector.normalize(raw)
            for draft in drafts:
                created_doc, created_version = await self._upsert_document(
                    draft, raw, external_object_id=persisted.id
                )
                if created_doc:
                    report.documents_created += 1
                if created_version:
                    report.versions_created += 1
                else:
                    report.versions_skipped += 1
        return report

    async def _upsert_raw_object(self, raw: RawExternalObject):  # type: ignore[return]
        return await self._ext_obj_repo.upsert(raw)

    async def _upsert_document(
        self,
        draft: CanonicalDocumentDraft,
        raw: RawExternalObject,
        external_object_id,
    ) -> tuple[bool, bool]:
        """Return (document_created, version_created)."""
        # 1. Find or create source
        source = await self._source_repo.get_by_external_object_id(external_object_id)
        if source is None:
            now = datetime.now(UTC)
            source = await self._source_repo.create_with_external_object(
                Source(
                    id=uuid4(),
                    source_type_raw="github",
                    source_type_canonical=SourceType.GIT_REPO,
                    origin=draft.provenance.external_url or draft.provenance.external_id,
                    created_at=now,
                    updated_at=now,
                ),
                external_object_id=external_object_id,
            )

        # 2. Find or create document
        doc_created = False
        doc = await self._doc_repo.get_by_source_kind_path(
            source.id,
            draft.document_kind,
            draft.logical_path or "",
        )
        if doc is None:
            now = datetime.now(UTC)
            doc = await self._doc_repo.create(
                Document(
                    id=uuid4(),
                    source_id=source.id,
                    title=draft.title,
                    path=draft.logical_path or "",
                    document_kind=draft.document_kind,
                    logical_path=draft.logical_path,
                    metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )
            doc_created = True

        # 3. Check idempotency via checksum
        latest = await self._dv_repo.get_latest_version(doc.id)
        if latest is not None and latest.checksum == draft.content_hash:
            return doc_created, False  # same content — skip

        # 4. Create new version with provenance snapshot in metadata
        max_version = await self._dv_repo.get_max_version(doc.id)
        provenance_snapshot = {
            "external_id": raw.external_id,
            "external_url": raw.external_url,
            "raw_payload_hash": raw.raw_payload_hash,
            "commit_sha": raw.metadata.get("commit_sha"),
            "path": raw.metadata.get("path"),
        }
        await self._dv_repo.create(
            DocumentVersion(
                id=uuid4(),
                document_id=doc.id,
                version=max_version + 1,
                content=draft.content,
                checksum=draft.content_hash,
                version_ref=draft.version_ref,
                source_updated_at=draft.source_updated_at,
                metadata=provenance_snapshot,
                created_at=datetime.now(UTC),
            )
        )
        return doc_created, True
```

- [ ] **Step 6: Run ingestion unit tests**

```
pytest tests/unit/ingestion/ -v
```
Expected: all PASSED

- [ ] **Step 7: Confirm import boundary still holds**

```
pytest tests/unit/connector_sdk/test_import_boundary.py -v
```
Expected: all PASSED (lore.ingestion does not import lore.connectors.github)

- [ ] **Step 8: Commit**

```bash
git add \
  lore/ingestion/models.py \
  lore/ingestion/service.py \
  tests/unit/ingestion/__init__.py \
  tests/unit/ingestion/_fakes.py \
  tests/unit/ingestion/test_ingest_idempotency.py \
  tests/unit/ingestion/test_ingest_new_version.py \
  tests/unit/ingestion/test_provenance_preserved.py
git commit -m "feat(ingestion): IngestionService with idempotency + provenance snapshot"
```

---

## Task 14: RepositoryImportService

**Files:**
- Create: `lore/ingestion/repository_import.py`

`RepositoryImportService` orchestrates the full import flow. It depends only on `BaseConnector` via `ConnectorRegistry`. It must not import `GitHubClient` or any concrete connector type.

- [ ] **Step 1: Implement repository_import.py**

```python
# lore/ingestion/repository_import.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from lore.connector_sdk.models import FullSyncRequest
from lore.connector_sdk.registry import ConnectorRegistry
from lore.ingestion.models import IngestionReport
from lore.ingestion.service import IngestionService

if TYPE_CHECKING:
    from lore.infrastructure.db.repositories.external_connection import (
        ExternalConnectionRepository,
    )
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )


@dataclass
class ImportResult:
    repository_id: UUID
    connector_id: str
    status: str
    report: IngestionReport


class RepositoryImportService:
    """Orchestrates: inspect_resource → full_sync → ingest. Provider-agnostic."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        ingestion: IngestionService,
        ext_connection_repo: ExternalConnectionRepository,
        ext_repository_repo: ExternalRepositoryRepository,
    ) -> None:
        self._registry = registry
        self._ingestion = ingestion
        self._ext_connection_repo = ext_connection_repo
        self._ext_repository_repo = ext_repository_repo

    async def import_repository(
        self,
        resource_uri: str,
        connector_id: str,
    ) -> ImportResult:
        connector = self._registry.get(connector_id)  # raises ConnectorNotFoundError if missing

        # 1. Get or create env-PAT connection record
        connection = await self._ext_connection_repo.get_or_create_env_pat(
            provider=connector_id
        )

        # 2. Inspect resource — provider-agnostic metadata fetch
        container_draft = await connector.inspect_resource(resource_uri)

        # 3. Get or create external repository record
        ext_repo = await self._ext_repository_repo.get_or_create(
            connection_id=connection.id,
            draft=container_draft,
        )

        # 4. Build sync request and run full sync
        request = FullSyncRequest(
            connection_id=connection.id,
            repository_id=ext_repo.id,
            resource_uri=resource_uri,
        )
        sync_result = await connector.full_sync(request)

        # 5. Ingest raw objects
        report = await self._ingestion.ingest_sync_result(sync_result, connector)

        # 6. Mark repository as synced
        await self._ext_repository_repo.mark_synced(ext_repo.id, datetime.now(UTC))

        return ImportResult(
            repository_id=ext_repo.id,
            connector_id=connector_id,
            status="synced",
            report=report,
        )
```

- [ ] **Step 2: Run all unit tests**

```
pytest tests/unit/ -v
```
Expected: all PASSED

- [ ] **Step 3: Commit**

```bash
git add lore/ingestion/repository_import.py
git commit -m "feat(ingestion): RepositoryImportService — provider-agnostic orchestration"
```

---

## Phase 4 complete

IngestionService and RepositoryImportService implemented and tested. Proceed to Phase 5: App Wiring + Tests.

Next plan file: `2026-05-11-github-connector-phase5-wiring-tests.md`
