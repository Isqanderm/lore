# Lore — AI-Native Memory Runtime

## What is Lore

Temporal memory and context engine for AI agents. Ingests code repos, markdown docs, ADRs, engineering discussions. Exposes hybrid retrieval for context assembly. NOT a chatbot, NOT a vector DB wrapper.

**Current stage:** v0.1 backend skeleton complete. No AI pipelines yet.

---

## Architecture: 4-layer modular monolith

```
lore/schema/        → pure cognitive model (frozen dataclasses, ZERO SQLAlchemy)
lore/domain/        → transformation functions ONLY (no new data structures)
lore/infrastructure → all external: ORM, DB, config, observability
apps/               → thin HTTP layer (FastAPI, stays thin)

Behavioral slices (ingestion/, retrieval/, graph/, etc.) → orchestration via service.py
```

### 8 Invariants — never violate

1. `lore/schema/` **never imports SQLAlchemy**
2. Behavioral slices **never touch ORM directly** — only through repositories
3. Repositories expose **dumb IO primitives only** — no ranking, fusion, intelligence
4. Intelligence (hybrid_search, reranking, fusion) lives in **`retrieval/service.py`**
5. `domain/` contains **only functions** that transform schema objects — no new classes
6. `Vector(3072)` exists **ONLY** in `lore/infrastructure/db/models/chunk.py`
7. `source_type_canonical` is **TEXT in DB** (soft constraint), NOT a PostgreSQL enum
8. `source_type_raw` always **preserves verbatim input** — never overwrite it

---

## Key technical decisions

| Decision | Choice | Reason |
|---|---|---|
| Embedding dims | 3072 | OpenAI text-embedding-3-large |
| HNSW index | Deferred | pgvector needs ≥0.8.0 for 3072-dim HNSW |
| GIN index | Present | Full-text search via tsvector works now |
| Docker image | `pgvector/pgvector:pg16` | `postgres:16` has no pgvector preinstalled |
| testcontainers | Same pgvector image | Consistency |
| `embedding_ref` | `"provider:model:version:sha256hash"` | Versioned, multi-model aware |
| SourceType in DB | TEXT not enum | New integrations require no DB migration |

---

## Project structure

```
apps/api/                   FastAPI factory, routes, middleware, exception handlers
apps/worker/                placeholder (future task queue)
apps/cli/                   placeholder

lore/schema/                Source, Document, DocumentVersion, Chunk, errors — NO SQLAlchemy
lore/domain/                normalize_source_type() — functions only
lore/ingestion/service.py   placeholder → chunking, idempotency, provenance (v0.2)
lore/extraction/service.py  placeholder → semantic extraction (v0.3)
lore/retrieval/service.py   placeholder → hybrid_search, reranking, fusion (v0.4)
lore/graph/                 placeholder → knowledge graph (v0.5)
lore/memory/                placeholder → memory management
lore/context/               placeholder → context assembly for agents (v1.0)
lore/freshness/             placeholder → temporal decay (v0.6)

lore/infrastructure/
  config.py                       Settings via pydantic-settings
  db/engine.py                    async SQLAlchemy engine
  db/session.py                   AsyncSession factory + FastAPI DI
  db/base.py                      DeclarativeBase
  db/models/source.py             SourceORM
  db/models/document.py           DocumentORM, DocumentVersionORM
  db/models/chunk.py              ChunkORM — Vector(3072), tsvector, GIN index
  db/repositories/base.py         BaseRepository[T]
  db/repositories/source.py       SourceRepository
  db/repositories/document.py     DocumentRepository, DocumentVersionRepository
  db/repositories/chunk.py        ChunkRepository — query_by_vector, query_by_text
  observability/logging.py        structlog configure_logging()
  observability/middleware.py     RequestIDMiddleware — binds request_id to structlog

tests/unit/                 pure logic, no DB, no mocks of internal code
tests/integration/          testcontainers real Postgres, session-scoped, rollback per test
tests/e2e/                  FastAPI TestClient, full request cycle
migrations/                 Alembic — 0001_initial_schema.py done
```

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

---

## Commands

```bash
make dev                   # docker-compose up + uvicorn reload
make test                  # all 3 levels
make test-unit             # pytest -m unit
make test-integration      # pytest -m integration  (requires Docker)
make test-e2e              # pytest -m e2e
make lint                  # ruff check
make format                # ruff format
make type-check            # mypy strict
make migrate               # alembic upgrade head
make migration name=<name> # new empty migration
```

---

## Testing conventions

- **Unit**: no DB, no HTTP, no external deps — pure Python logic only
- **Integration**: session-scoped testcontainers fixture (`pgvector/pgvector:pg16`), `session.rollback()` after each test
- **E2E**: `TestClient(create_app())`, tests the full FastAPI request cycle
- Markers: `@pytest.mark.unit` / `@pytest.mark.integration` / `@pytest.mark.e2e`
- `asyncio_mode = "auto"`, session loop scope
- mypy overrides `disallow_untyped_decorators = false` for `tests.*`

---

## API conventions

- Versioned routing: `/api/v1/...`
- Error format always: `{"error": {"code": "snake_case_code", "message": "Human readable"}}`
- Every request gets `X-Request-ID` (read from header or generated as UUID4)
- All log entries include `request_id` automatically via structlog contextvars

---

## Adding new features

### New behavioral slice (e.g. `lore/graph/`)
Use skill: `add-behavioral-slice`

### New ORM model + repository
Use skill: `add-repository`

### New API endpoint
- Add router in `apps/api/routes/v1/<name>.py`
- Mount in `apps/api/main.py`
- Keep route handler thin — no business logic, only call service/repository

---

## Future roadmap

| Version | Feature |
|---|---|
| v0.2 | Ingestion pipeline — chunking strategy, idempotency, provenance tracking |
| v0.3 | Embedding pipeline — OpenAI async jobs, embedding_ref population |
| v0.4 | Hybrid retrieval — vector + full-text fusion, reranking in retrieval/service.py |
| v0.5 | Knowledge graph — entity extraction, assertion generation |
| v0.6 | Temporal freshness — decay model, staleness detection |
| v1.0 | Context assembly API for AI agents |
