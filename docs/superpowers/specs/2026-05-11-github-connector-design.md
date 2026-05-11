# Lore — GitHub Connector Foundation Design Spec

**Date:** 2026-05-11
**Status:** Approved
**Scope:** Connector SDK + GitHub Connector MVP (v0.2 foundation)

---

## 1. Overview

This spec defines the architectural foundation for pluggable connectors in Lore, starting with a GitHub connector. The goal is to establish clean boundaries between:

- **Connector SDK** — stable contract layer
- **GitHub Connector** — provider-specific integration
- **Integration Layer** — external state (connections, repositories, raw objects)
- **Lore Core Memory Layer** — canonical knowledge (sources, documents, versions, chunks)
- **Ingestion Service** — orchestration between integration and memory layers

The GitHub connector fetches repository files and metadata, produces `RawExternalObject` records, which the ingestion service normalizes into `CanonicalDocumentDraft` and persists as `sources → documents → document_versions`.

**Non-goals for this iteration:**
- Embeddings, graph reasoning, documentation generation
- Full issues/PR ingestion (architecture ready, not implemented)
- Webhook live verification
- GitHub App auth
- Multi-tenant credentials storage
- Connector marketplace or separate packages

---

## 2. Layer Model and Import Rules

### Data flow

```
external_connections     ← GitHub auth config (auth_mode="env_pat")
      ↓
external_repositories    ← GitHub repo metadata (owner/name/branch)
      ↓
external_objects         ← raw fetched objects (files, repository metadata)
      ↓ FK (sources.external_object_id)
sources                  ← Lore provenance record (provider-agnostic)
      ↓ FK
documents                ← canonical knowledge unit
      ↓ FK
document_versions        ← temporal versions (immutable content history)
      ↓ FK
chunks                   ← retrieval units (unchanged in this spec)
```

### Two logical layers

**Integration Layer** (provider-specific state):
- `external_connections` — authentication/installation config
- `external_repositories` — provider-specific containers
- `external_objects` — raw fetched provider objects

**Lore Core Memory Layer** (provider-agnostic knowledge):
- `sources` — internal provenance abstraction
- `documents` — normalized knowledge units
- `document_versions` — temporal history (immutable versions)
- `chunks` — retrieval units

### Import direction rules

Higher-level layers may import lower-level layers. The reverse is forbidden.

```
apps/api
  → lore/connectors/github     (ONLY composition root may import concrete connectors)
  → lore/ingestion
  → lore/infrastructure
  → lore/schema

lore/ingestion
  → lore/connector_sdk          (abstractions only, never concrete connectors)
  → lore/infrastructure
  → lore/schema

lore/connectors/github
  → lore/connector_sdk
  → lore/schema

lore/connector_sdk
  → lore/schema                 (or standalone types)

lore/schema
  → stdlib only
```

**Critical invariant:** You can delete `lore/connectors/github/` and `lore/schema`, `lore/connector_sdk`, `lore/ingestion` must not break on imports.

---

## 3. Connector SDK (`lore/connector_sdk/`)

### 3.1 `base.py`

```python
class BaseConnector(ABC):
    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest: ...

    @property
    def connector_id(self) -> str:
        return self.manifest.connector_id

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

### 3.2 `models.py`

```python
@dataclass(frozen=True)
class FullSyncRequest:
    connection_id: UUID
    repository_id: UUID | None
    resource_uri: str            # "https://github.com/owner/repo"
    options: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RawExternalObject:
    provider: str                # "github"
    object_type: str             # "github.file", "github.repository"
    external_id: str             # stable: "owner/repo:file:path"
    external_url: str | None     # human URL: blob/{commit_sha}/path
    connection_id: UUID
    repository_id: UUID | None
    raw_payload: dict[str, Any]
    raw_payload_hash: str        # sha256(json(raw_payload)), always present
    content: str | None          # decoded text content, nullable
    content_hash: str | None     # sha256(content) if content is not None
    source_updated_at: datetime | None
    fetched_at: datetime
    metadata: dict[str, Any]    # commit_sha, path, size, branch, owner, repo

@dataclass(frozen=True)
class CanonicalDocumentDraft:
    document_kind: str           # "documentation.readme", "code.file", ...
    logical_path: str | None     # file path, or None for non-file objects
    title: str
    content: str
    content_hash: str            # maps to document_versions.checksum in DB
    version_ref: str | None      # commit SHA for files
    source_updated_at: datetime | None
    provenance: ProvenanceDraft
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
class SyncResult:
    connector_id: str
    raw_objects: list[RawExternalObject]
    cursor: SyncCursor | None = None
    has_more: bool = False
    warnings: list[str] = field(default_factory=list)
```

**SDK field → DB field alias:**

| SDK | DB column | Meaning |
|---|---|---|
| `CanonicalDocumentDraft.content_hash` | `document_versions.checksum` | Deterministic hash of canonical content |

Do not add `content_hash` to `document_versions`. The existing `checksum` column serves this purpose.

### 3.3 `manifest.py` + `capabilities.py`

```python
@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    display_name: str
    version: str
    capabilities: ConnectorCapabilities

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

### 3.4 `errors.py`

```python
class ConnectorError(Exception): ...
class ConnectorConfigurationError(ConnectorError): ...
class ConnectorAuthenticationError(ConnectorError): ...
class ConnectorRateLimitError(ConnectorError): ...
class ConnectorNotFoundError(ConnectorError): ...
class ExternalResourceNotFoundError(ConnectorError): ...
class UnsupportedCapabilityError(ConnectorError): ...
```

### 3.5 `registry.py`

```python
class ConnectorRegistry:
    def register(self, connector: BaseConnector) -> None: ...
    def get(self, connector_id: str) -> BaseConnector: ...   # raises ConnectorNotFoundError
    def list(self) -> list[ConnectorManifest]: ...
    def has(self, connector_id: str) -> bool: ...
```

Registration happens exclusively in `apps/api/lifespan.py` (composition root).

---

## 4. GitHub Connector (`lore/connectors/github/`)

### 4.1 Module structure

```
lore/connectors/github/
    __init__.py
    manifest.py        ConnectorManifest with MVP capabilities
    connector.py       GitHubConnector(BaseConnector)
    client.py          GitHubClient — async HTTP via httpx
    auth.py            GitHubAuth — reads GITHUB_TOKEN from settings
    file_policy.py     FileSelectionPolicy — include/exclude rules
    normalizer.py      GitHubNormalizer — RawExternalObject → list[CanonicalDocumentDraft]
    webhook.py         skeleton: verify_webhook / parse_webhook raise UnsupportedCapabilityError
    models.py          GitHubRepoRef, GitHubTreeEntry (internal, not exported)
```

### 4.2 MVP Capabilities

```python
ConnectorCapabilities(
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
```

Capabilities must honestly reflect what is implemented.

### 4.3 `auth.py`

```python
@dataclass(frozen=True)
class GitHubAuth:
    token: str
    auth_mode: str = "env_pat"

    @classmethod
    def from_settings(cls, settings: Settings) -> "GitHubAuth":
        if not settings.github_token:
            raise ConnectorConfigurationError("GITHUB_TOKEN is not set")
        return cls(token=settings.github_token.get_secret_value())
```

Token is never logged, never stored in DB, never included in error messages or API responses.

`external_connections` for env PAT stores:
```json
{
  "provider": "github",
  "auth_mode": "env_pat",
  "metadata": {"token_source": "env", "configured": true}
}
```

### 4.4 `client.py`

```python
class GitHubClient:
    async def get_repository(self, owner: str, repo: str) -> dict[str, Any]: ...
    async def get_repository_tree(self, owner: str, repo: str, branch: str) -> list[GitHubTreeEntry]:
        # resolves internally: branch → commit SHA → tree SHA → recursive tree
        ...
    async def get_branch_head_sha(self, owner: str, repo: str, branch: str) -> str: ...
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        # decodes base64, rejects binary/non-UTF-8 safely
        ...
```

HTTP error mapping:
- 401/403 → `ConnectorAuthenticationError`
- 404 → `ExternalResourceNotFoundError`
- 429/rate-limited → `ConnectorRateLimitError`
- 5xx → `ConnectorError`

### 4.5 `file_policy.py`

```python
@dataclass
class FileSelectionPolicy:
    max_file_size_bytes: int = 500_000
    # include/exclude patterns configurable at construction time

    def should_include(self, entry: GitHubTreeEntry) -> bool: ...
    def filter(self, entries: list[GitHubTreeEntry]) -> list[GitHubTreeEntry]: ...
```

Default includes: `README*`, `docs/**`, `*.md`, `pyproject.toml`, `package.json`,
`Dockerfile`, `docker-compose.yml`, `.github/workflows/**`, `src/**`, `app/**`, `lib/**`,
`packages/**`, `tests/**`, `lore/**`

Default excludes: `node_modules/`, `dist/`, `build/`, `.git/`, `vendor/`, `coverage/`,
binary files, non-UTF-8, files > `max_file_size_bytes`

### 4.6 `connector.py`

```python
class GitHubConnector(BaseConnector):
    def __init__(
        self,
        client: GitHubClient,
        file_policy: FileSelectionPolicy,
        normalizer: GitHubNormalizer,
    ):
        ...

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        owner, repo = parse_github_url(request.resource_uri)
        repo_meta = await self.client.get_repository(owner, repo)
        branch = repo_meta["default_branch"]
        head_sha = await self.client.get_branch_head_sha(owner, repo, branch)

        # 1. github.repository raw object
        repo_raw = self._build_repo_raw_object(repo_meta, request, head_sha)

        # 2. github.file raw objects
        tree = await self.client.get_repository_tree(owner, repo, branch)
        selected = self.file_policy.filter(tree)
        file_raws = []
        for entry in selected:
            content = await self.client.get_file_content(owner, repo, entry.path, head_sha)
            file_raws.append(self._build_file_raw_object(entry, content, request, owner, repo, branch, head_sha))

        return SyncResult(connector_id="github", raw_objects=[repo_raw, *file_raws])

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return self.normalizer.normalize(raw)
```

`external_id` rules:
- Repository: `"{owner}/{repo}:repository"`
- File: `"{owner}/{repo}:file:{path}"` (stable by path, not blob SHA)

`external_url` for files: `https://github.com/{owner}/{repo}/blob/{commit_sha}/{path}` (human URL with commit SHA)

`metadata` for files must include: `owner`, `repo`, `branch`, `commit_sha`, `path`, `size`

### 4.7 `normalizer.py`

```python
class GitHubNormalizer:
    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        if raw.object_type == "github.file":
            return [self._normalize_file(raw)]
        elif raw.object_type == "github.repository":
            return []  # future: repository brief artifact
        return []
```

Document kind mapping for `github.file`:

| File pattern | `document_kind` |
|---|---|
| `README*` | `documentation.readme` |
| `docs/**/*.md`, `*.md` | `documentation.markdown` |
| `tests/**/*.py`, `test_*.py`, `*_test.py` | `code.test` |
| `**/*.py` | `code.file` |
| `pyproject.toml`, `package.json`, `setup.cfg` | `config.build` |
| `Dockerfile`, `docker-compose.yml` | `config.runtime` |
| `.github/workflows/**/*.yml` | `config.ci` |
| other | `code.file` |

`version_ref` for files: `metadata["commit_sha"]`

### 4.8 `webhook.py` (skeleton)

Both `verify_webhook` and `parse_webhook` raise `UnsupportedCapabilityError`.
`supports_webhooks=False` in manifest. No fake `return True`.

---

## 5. Storage Changes

### 5.1 New tables (migration 0002 — Integration Layer)

```sql
CREATE TABLE external_connections (
    id UUID PRIMARY KEY,
    provider TEXT NOT NULL,
    auth_mode TEXT NOT NULL,
    external_account_id TEXT,
    installation_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE external_repositories (
    id UUID PRIMARY KEY,
    connection_id UUID NOT NULL REFERENCES external_connections(id),
    provider TEXT NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    default_branch TEXT NOT NULL,
    html_url TEXT NOT NULL,
    visibility TEXT,
    last_synced_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE external_objects (
    id UUID PRIMARY KEY,
    repository_id UUID REFERENCES external_repositories(id),
    connection_id UUID NOT NULL REFERENCES external_connections(id),
    provider TEXT NOT NULL,
    object_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_url TEXT,
    raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_payload_hash TEXT NOT NULL,
    content TEXT,
    content_hash TEXT,
    source_updated_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_external_objects_connection_provider_id
        UNIQUE (connection_id, provider, external_id)
);
```

`external_objects` stores the **latest fetched raw state** per `external_id`. Temporal content history lives in `document_versions`. No `external_object_versions` table for now.

### 5.2 Existing table evolution (migration 0002 continued)

All new columns are nullable to avoid breaking existing data and tests.

```sql
-- sources: link to integration layer
ALTER TABLE sources
    ADD COLUMN external_object_id UUID REFERENCES external_objects(id);
-- NOT unique: one external_object may produce multiple sources/documents

-- documents: canonical knowledge fields
ALTER TABLE documents
    ADD COLUMN document_kind TEXT,
    ADD COLUMN logical_path TEXT,
    ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
-- documents.title already exists

-- document_versions: temporal and versioning fields
ALTER TABLE document_versions
    ADD COLUMN version_ref TEXT,
    ADD COLUMN source_updated_at TIMESTAMPTZ,
    ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
-- document_versions.checksum already serves as content_hash
-- SDK field CanonicalDocumentDraft.content_hash maps to DB column checksum
-- Do not add a separate content_hash column
```

### 5.3 Indexes (migration 0002)

```sql
CREATE INDEX ix_external_repositories_provider_full_name
    ON external_repositories(provider, full_name);
CREATE INDEX ix_external_objects_repository_id
    ON external_objects(repository_id);
CREATE INDEX ix_external_objects_provider_object_type
    ON external_objects(provider, object_type);
CREATE INDEX ix_sources_external_object_id
    ON sources(external_object_id);
CREATE INDEX ix_documents_document_kind
    ON documents(document_kind);
CREATE INDEX ix_documents_logical_path
    ON documents(logical_path);
CREATE INDEX ix_document_versions_content_hash
    ON document_versions(checksum);
CREATE INDEX ix_document_versions_version_ref
    ON document_versions(version_ref);
```

---

## 6. Application Wiring

### 6.1 Settings

Add to `lore/infrastructure/config.py`:
```python
github_token: SecretStr | None = None  # GITHUB_TOKEN env var
```

### 6.2 ConnectorRegistry in lifespan

```python
# apps/api/lifespan.py — ONLY place that imports concrete connectors
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    registry = ConnectorRegistry()
    registry.register(GitHubConnector(
        client=GitHubClient.from_settings(settings),
        file_policy=FileSelectionPolicy(),
        normalizer=GitHubNormalizer(),
    ))
    app.state.connector_registry = registry
    yield
```

### 6.3 RepositoryImportService

```
POST /api/v1/repositories/import
  1. parse resource_uri → validate GitHub URL
  2. get_or_create external_connection (provider=github, auth_mode=env_pat)
  3. fetch repo metadata via GitHubClient
  4. get_or_create external_repository (connection_id, full_name, ...)
  5. build FullSyncRequest(connection_id, repository_id, resource_uri)
  6. connector.full_sync(request) → SyncResult
  7. ingestion.ingest_sync_result(sync_result, connector) → IngestionReport
  8. update external_repository.last_synced_at
  9. return {repository_id, status: "synced", connector: "github"}
```

`GitHubConnector` does **not** create DB records. All persistence is in `RepositoryImportService` and `IngestionService`.

### 6.4 IngestionService

```python
class IngestionService:
    async def ingest_sync_result(
        self,
        sync_result: SyncResult,
        connector: BaseConnector,   # BaseConnector, not concrete type
    ) -> IngestionReport:
        for raw in sync_result.raw_objects:
            persisted_obj = await self._upsert_raw_object(raw)
            drafts = connector.normalize(raw)
            for draft in drafts:
                await self._upsert_document(draft, raw, external_object_id=persisted_obj.id)

    async def _upsert_raw_object(self, raw: RawExternalObject) -> PersistedExternalObject:
        # upsert on (connection_id, provider, external_id)
        # returns persisted record with id

    async def _upsert_document(
        self,
        draft: CanonicalDocumentDraft,
        raw: RawExternalObject,
        external_object_id: UUID,
    ) -> None:
        # 1. find or create source (source.external_object_id = external_object_id)
        # 2. find or create document (by source_id + document_kind + logical_path)
        # 3. get latest document_version.checksum
        # 4. if same as draft.content_hash → skip (idempotency)
        # 5. if different (or no version yet) → create new DocumentVersion
        #    version = max(existing) + 1
        #    checksum = draft.content_hash
        #    version_ref = draft.version_ref
        #    source_updated_at = draft.source_updated_at
```

### 6.5 API Endpoints

```
POST /api/v1/repositories/import
GET  /api/v1/connectors
GET  /api/v1/repositories/{id}
POST /api/v1/connectors/{connector_id}/webhook  (skeleton, raises 501)
```

---

## 7. Testing Strategy

### 7.1 All default tests must be hermetic

No real GitHub API calls in `unit`, `integration`, or `e2e` suites. Use fake connectors and mocked clients.

Live GitHub smoke tests are opt-in:
```
tests/smoke/test_github_live_import.py
@pytest.mark.live_github
# Runs only when GITHUB_TOKEN and LIVE_GITHUB_TEST_REPO are set
```

### 7.2 Unit tests

`tests/unit/connectors/github/`:
- `test_url_parser` — valid https, git@, invalid URLs
- `test_file_policy` — includes/excludes, size limit, binary rejection
- `test_raw_object_hashing` — `raw_payload_hash` and `content_hash` are deterministic; `external_id` stable
- `test_github_normalizer` — README→readme, *.py→code.file, tests/→code.test, pyproject.toml→config.build, workflow→config.ci

`tests/unit/connector_sdk/`:
- `test_connector_registry` — register/get/list/has, `ConnectorNotFoundError`
- `test_import_boundary` — importing `lore.schema`, `lore.connector_sdk`, `lore.ingestion` must not trigger import of `lore.connectors.github`

`tests/unit/ingestion/`:
- `test_ingest_idempotency` — same `content_hash` does not create a duplicate `DocumentVersion`
- `test_ingest_new_version` — changed content creates a new `DocumentVersion`
- `test_provenance_preserved` — `external_object_id`, `version_ref` are correctly linked

### 7.3 Integration tests

`tests/integration/connectors/`:
- `test_repository_import_flow` — full flow: `external_connection → external_repository → external_objects → sources → documents → document_versions`
- `test_ingest_idempotency_db` — repeated sync with same content produces no duplicates in DB

### 7.4 E2E tests

`tests/e2e/`:
- `test_import_endpoint` — `POST /api/v1/repositories/import` with fake connector returns 200 + `repository_id`
- `test_connectors_endpoint` — `GET /api/v1/connectors` returns GitHub manifest

---

## 8. Next Steps (intentionally unimplemented)

| Feature | When |
|---|---|
| GitHub App auth (installation tokens) | After multi-user is needed |
| Issues / PR ingestion | v0.3 |
| Webhook live processing | After incremental sync |
| Stale docs detection | v0.6 |
| Repository Brief artifact | v0.5+ |
| Filesystem connector | Second connector to validate SDK contracts |
| Incremental sync with SyncCursor | After full sync is stable |

---

## 9. Key Architectural Rules (invariants for this spec)

1. `lore/connectors/github/` may be deleted; `lore/schema`, `lore/connector_sdk`, `lore/ingestion` must not break on imports.
2. `GitHubConnector` never creates DB records. It fetches + returns `RawExternalObject` + normalizes.
3. `IngestionService` depends on `BaseConnector`, not `GitHubConnector`.
4. `apps/api/lifespan.py` is the only module that may import `lore.connectors.github`.
5. `sources.external_object_id` is nullable — sources may exist without a connector origin.
6. `document_versions.checksum` is the DB representation of `content_hash`. No duplicate field.
7. `external_id` for files is stable by path: `{owner}/{repo}:file:{path}`.
8. `commit_sha` is mandatory in `RawExternalObject.metadata` for file objects. It is provenance core.
9. All tests are hermetic by default. No real GitHub calls except `@pytest.mark.live_github`.
10. Connector capabilities must only advertise implemented features.
