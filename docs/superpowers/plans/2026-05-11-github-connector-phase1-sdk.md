# GitHub Connector Foundation — Phase 1: Connector SDK

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `lore/connector_sdk/` — the stable contract layer between Lore Core and any connector.

**Architecture:** Pure Python dataclasses and ABCs. Zero SQLAlchemy, zero FastAPI. Importable without any infrastructure.

**Tech Stack:** Python 3.12 stdlib only (dataclasses, abc, uuid, datetime, typing)

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Create | `lore/connector_sdk/__init__.py` | public re-exports |
| Create | `lore/connector_sdk/errors.py` | ConnectorError hierarchy |
| Create | `lore/connector_sdk/capabilities.py` | ConnectorCapabilities dataclass |
| Create | `lore/connector_sdk/manifest.py` | ConnectorManifest dataclass |
| Create | `lore/connector_sdk/models.py` | RawExternalObject, CanonicalDocumentDraft, ProvenanceDraft, SyncResult, SyncCursor, WebhookEvent, FullSyncRequest, IncrementalSyncRequest, ExternalContainerDraft |
| Create | `lore/connector_sdk/base.py` | BaseConnector ABC |
| Create | `lore/connector_sdk/registry.py` | ConnectorRegistry |
| Create | `tests/unit/connector_sdk/__init__.py` | test package |
| Create | `tests/unit/connector_sdk/test_registry.py` | registry unit tests |
| Create | `tests/unit/connector_sdk/test_import_boundary.py` | import isolation test |

---

## Task 1: errors, capabilities, manifest, models

**Files:**
- Create: `lore/connector_sdk/errors.py`
- Create: `lore/connector_sdk/capabilities.py`
- Create: `lore/connector_sdk/manifest.py`
- Create: `lore/connector_sdk/models.py`
- Test: `tests/unit/connector_sdk/test_registry.py` (written in Task 2, referenced here for context)

- [ ] **Step 1: Write a failing smoke test for SDK imports**

```python
# tests/unit/connector_sdk/__init__.py  (empty file)
```

```python
# tests/unit/connector_sdk/test_registry.py
import pytest
from lore.connector_sdk.errors import (
    ConnectorError,
    ConnectorAuthenticationError,
    ConnectorConfigurationError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ExternalResourceNotFoundError,
    UnsupportedCapabilityError,
)
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest


def test_error_hierarchy() -> None:
    assert issubclass(ConnectorAuthenticationError, ConnectorError)
    assert issubclass(ConnectorConfigurationError, ConnectorError)
    assert issubclass(ConnectorNotFoundError, ConnectorError)
    assert issubclass(ConnectorRateLimitError, ConnectorError)
    assert issubclass(ExternalResourceNotFoundError, ConnectorError)
    assert issubclass(UnsupportedCapabilityError, ConnectorError)


def test_capabilities_frozen() -> None:
    caps = ConnectorCapabilities(
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
    )
    with pytest.raises(AttributeError):
        caps.supports_full_sync = False  # type: ignore[misc]


def test_manifest_frozen() -> None:
    caps = ConnectorCapabilities(
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
        object_types=["github.file"],
    )
    m = ConnectorManifest(
        connector_id="github",
        display_name="GitHub",
        version="0.1.0",
        capabilities=caps,
    )
    assert m.connector_id == "github"
    with pytest.raises(AttributeError):
        m.connector_id = "other"  # type: ignore[misc]
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/connector_sdk/test_registry.py -v
```
Expected: `ModuleNotFoundError: No module named 'lore.connector_sdk'`

- [ ] **Step 3: Implement errors.py**

```python
# lore/connector_sdk/errors.py


class ConnectorError(Exception):
    """Base error for all connector failures."""


class ConnectorConfigurationError(ConnectorError):
    """Connector is misconfigured (missing token, invalid setting)."""


class ConnectorAuthenticationError(ConnectorError):
    """Authentication to the external provider failed (401/403)."""


class ConnectorRateLimitError(ConnectorError):
    """External provider rate limit hit (429)."""


class ConnectorNotFoundError(ConnectorError):
    """Requested connector_id is not registered in the registry."""


class ExternalResourceNotFoundError(ConnectorError):
    """Resource URL returned 404 from the external provider."""


class UnsupportedCapabilityError(ConnectorError):
    """Connector does not support this capability."""
```

- [ ] **Step 4: Implement capabilities.py**

```python
# lore/connector_sdk/capabilities.py
from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectorCapabilities:
    supports_full_sync: bool
    supports_incremental_sync: bool
    supports_webhooks: bool
    supports_repository_tree: bool
    supports_files: bool
    supports_issues: bool
    supports_pull_requests: bool
    supports_comments: bool
    supports_releases: bool
    supports_permissions: bool
    object_types: list[str]
```

- [ ] **Step 5: Implement manifest.py**

```python
# lore/connector_sdk/manifest.py
from dataclasses import dataclass

from lore.connector_sdk.capabilities import ConnectorCapabilities


@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    display_name: str
    version: str
    capabilities: ConnectorCapabilities
```

- [ ] **Step 6: Implement models.py**

```python
# lore/connector_sdk/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class FullSyncRequest:
    connection_id: UUID
    repository_id: UUID | None
    resource_uri: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IncrementalSyncRequest:
    connection_id: UUID
    repository_id: UUID | None
    resource_uri: str
    cursor: SyncCursor
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SyncCursor:
    value: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEvent:
    event_type: str
    provider: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalContainerDraft:
    provider: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    html_url: str
    visibility: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProvenanceDraft:
    provider: str
    external_id: str
    external_url: str | None
    connection_id: UUID
    repository_id: UUID | None
    raw_payload_hash: str


@dataclass(frozen=True)
class RawExternalObject:
    provider: str
    object_type: str
    external_id: str
    external_url: str | None
    connection_id: UUID
    repository_id: UUID | None
    raw_payload: dict[str, Any]
    raw_payload_hash: str  # sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str))
    content: str | None
    content_hash: str | None  # sha256(content) if content is not None
    source_updated_at: datetime | None
    fetched_at: datetime
    metadata: dict[str, Any]  # commit_sha, path, size, branch, owner, repo


@dataclass(frozen=True)
class CanonicalDocumentDraft:
    document_kind: str
    logical_path: str | None
    title: str
    content: str
    content_hash: str  # maps to document_versions.checksum in DB
    version_ref: str | None
    source_updated_at: datetime | None
    provenance: ProvenanceDraft
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SyncResult:
    connector_id: str
    raw_objects: list[RawExternalObject]
    cursor: SyncCursor | None = None
    has_more: bool = False
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 7: Run tests — should pass**

```
pytest tests/unit/connector_sdk/test_registry.py::test_error_hierarchy tests/unit/connector_sdk/test_registry.py::test_capabilities_frozen tests/unit/connector_sdk/test_registry.py::test_manifest_frozen -v
```
Expected: 3 PASSED

- [ ] **Step 8: Commit**

```bash
git add lore/connector_sdk/errors.py lore/connector_sdk/capabilities.py lore/connector_sdk/manifest.py lore/connector_sdk/models.py tests/unit/connector_sdk/__init__.py tests/unit/connector_sdk/test_registry.py
git commit -m "feat(sdk): connector SDK errors, capabilities, manifest, models"
```

---

## Task 2: BaseConnector ABC + ConnectorRegistry

**Files:**
- Create: `lore/connector_sdk/base.py`
- Create: `lore/connector_sdk/registry.py`
- Create: `lore/connector_sdk/__init__.py`
- Modify: `tests/unit/connector_sdk/test_registry.py` (add registry + base tests)

- [ ] **Step 1: Add registry and base tests to test_registry.py**

Append to `tests/unit/connector_sdk/test_registry.py`:

```python
from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.registry import ConnectorRegistry


def _make_caps(**overrides: bool) -> ConnectorCapabilities:
    defaults = dict(
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
    )
    defaults.update(overrides)  # type: ignore[arg-type]
    return ConnectorCapabilities(**defaults)  # type: ignore[arg-type]


class _StubConnector(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="stub",
            display_name="Stub",
            version="0.0.1",
            capabilities=_make_caps(),
        )


def test_registry_register_and_get() -> None:
    reg = ConnectorRegistry()
    stub = _StubConnector()
    reg.register(stub)
    assert reg.get("stub") is stub


def test_registry_has() -> None:
    reg = ConnectorRegistry()
    assert not reg.has("stub")
    reg.register(_StubConnector())
    assert reg.has("stub")


def test_registry_list() -> None:
    reg = ConnectorRegistry()
    reg.register(_StubConnector())
    manifests = reg.list()
    assert len(manifests) == 1
    assert manifests[0].connector_id == "stub"


def test_registry_get_unknown_raises() -> None:
    reg = ConnectorRegistry()
    with pytest.raises(ConnectorNotFoundError):
        reg.get("missing")


def test_base_connector_unsupported_capabilities() -> None:
    stub = _StubConnector()
    with pytest.raises(UnsupportedCapabilityError):
        import asyncio
        asyncio.run(stub.full_sync(None))  # type: ignore[arg-type]
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/connector_sdk/test_registry.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` for `base`, `registry`

- [ ] **Step 3: Implement base.py**

```python
# lore/connector_sdk/base.py
from __future__ import annotations

from abc import ABC, abstractmethod

from lore.connector_sdk.errors import UnsupportedCapabilityError
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    IncrementalSyncRequest,
    RawExternalObject,
    SyncResult,
    WebhookEvent,
)


class BaseConnector(ABC):
    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest: ...

    @property
    def connector_id(self) -> str:
        return self.manifest.connector_id

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        raise UnsupportedCapabilityError("inspect_resource")

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raise UnsupportedCapabilityError("full_sync")

    async def incremental_sync(self, request: IncrementalSyncRequest) -> SyncResult:
        raise UnsupportedCapabilityError("incremental_sync")

    async def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        raise UnsupportedCapabilityError("webhooks")

    async def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
        raise UnsupportedCapabilityError("webhooks")

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        raise UnsupportedCapabilityError("normalization")
```

- [ ] **Step 4: Implement registry.py**

```python
# lore/connector_sdk/registry.py
from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.errors import ConnectorNotFoundError
from lore.connector_sdk.manifest import ConnectorManifest


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        self._connectors[connector.connector_id] = connector

    def get(self, connector_id: str) -> BaseConnector:
        if connector_id not in self._connectors:
            raise ConnectorNotFoundError(f"Connector '{connector_id}' is not registered")
        return self._connectors[connector_id]

    def list(self) -> list[ConnectorManifest]:
        return [c.manifest for c in self._connectors.values()]

    def has(self, connector_id: str) -> bool:
        return connector_id in self._connectors
```

- [ ] **Step 5: Create __init__.py with public exports**

```python
# lore/connector_sdk/__init__.py
from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.errors import (
    ConnectorAuthenticationError,
    ConnectorConfigurationError,
    ConnectorError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ExternalResourceNotFoundError,
    UnsupportedCapabilityError,
)
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    IncrementalSyncRequest,
    ProvenanceDraft,
    RawExternalObject,
    SyncCursor,
    SyncResult,
    WebhookEvent,
)
from lore.connector_sdk.registry import ConnectorRegistry

__all__ = [
    "BaseConnector",
    "CanonicalDocumentDraft",
    "ConnectorAuthenticationError",
    "ConnectorCapabilities",
    "ConnectorConfigurationError",
    "ConnectorError",
    "ConnectorManifest",
    "ConnectorNotFoundError",
    "ConnectorRateLimitError",
    "ConnectorRegistry",
    "ExternalContainerDraft",
    "ExternalResourceNotFoundError",
    "FullSyncRequest",
    "IncrementalSyncRequest",
    "ProvenanceDraft",
    "RawExternalObject",
    "SyncCursor",
    "SyncResult",
    "UnsupportedCapabilityError",
    "WebhookEvent",
]
```

- [ ] **Step 6: Run all SDK tests**

```
pytest tests/unit/connector_sdk/ -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add lore/connector_sdk/base.py lore/connector_sdk/registry.py lore/connector_sdk/__init__.py tests/unit/connector_sdk/test_registry.py
git commit -m "feat(sdk): BaseConnector ABC and ConnectorRegistry"
```

---

## Task 3: Import boundary test

**Files:**
- Create: `tests/unit/connector_sdk/test_import_boundary.py`

This test verifies that deleting `lore/connectors/github/` would not break `lore.schema`, `lore.connector_sdk`, or `lore.ingestion` imports. It works by asserting that none of those modules transitively import anything from `lore.connectors`.

- [ ] **Step 1: Write the test**

```python
# tests/unit/connector_sdk/test_import_boundary.py
"""
Verifies the import isolation invariant:
  lore.schema, lore.connector_sdk, lore.ingestion
  must NOT transitively import lore.connectors.github.
If this test fails, a boundary violation was introduced.
"""
import sys
import importlib


def _get_all_imported_modules(root_module: str) -> set[str]:
    """Import root_module and return the set of all sys.modules keys added."""
    before = set(sys.modules.keys())
    importlib.import_module(root_module)
    after = set(sys.modules.keys())
    return after - before


def test_schema_does_not_import_github() -> None:
    # Clear any cached imports for isolation
    to_remove = [k for k in sys.modules if k.startswith("lore.schema")]
    for k in to_remove:
        del sys.modules[k]

    new_modules = _get_all_imported_modules("lore.schema")
    github_imports = {m for m in new_modules if "lore.connectors" in m}
    assert not github_imports, (
        f"lore.schema transitively imports lore.connectors: {github_imports}"
    )


def test_connector_sdk_does_not_import_github() -> None:
    to_remove = [k for k in sys.modules if k.startswith("lore.connector_sdk")]
    for k in to_remove:
        del sys.modules[k]

    new_modules = _get_all_imported_modules("lore.connector_sdk")
    github_imports = {m for m in new_modules if "lore.connectors" in m}
    assert not github_imports, (
        f"lore.connector_sdk transitively imports lore.connectors: {github_imports}"
    )


def test_ingestion_does_not_import_github() -> None:
    to_remove = [k for k in sys.modules if k.startswith("lore.ingestion")]
    for k in to_remove:
        del sys.modules[k]

    new_modules = _get_all_imported_modules("lore.ingestion")
    github_imports = {m for m in new_modules if "lore.connectors" in m}
    assert not github_imports, (
        f"lore.ingestion transitively imports lore.connectors: {github_imports}"
    )
```

- [ ] **Step 2: Run to confirm tests pass**

```
pytest tests/unit/connector_sdk/test_import_boundary.py -v
```
Expected: 3 PASSED (lore.connectors.github doesn't exist yet, so definitely no transitive import)

- [ ] **Step 3: Run full unit suite to confirm nothing broken**

```
pytest tests/unit/ -v
```
Expected: all PASSED

- [ ] **Step 4: Commit**

```bash
git add tests/unit/connector_sdk/test_import_boundary.py
git commit -m "test(sdk): import boundary invariant — connectors.github must not leak into core"
```

---

## Phase 1 complete

After Task 3, `lore/connector_sdk/` is fully implemented and tested. Proceed to Phase 2: Storage (migration + ORM models + repositories).

Next plan file: `2026-05-11-github-connector-phase2-storage.md`
