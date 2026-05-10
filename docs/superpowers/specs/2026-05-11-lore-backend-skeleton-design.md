# Lore — Backend Skeleton Design Spec

**Date:** 2026-05-11  
**Status:** Approved  
**Scope:** Initial backend foundation (v0.1)

---

## 1. Overview

Lore is a temporal memory and context engine for AI agents. It ingests code repositories, markdown documentation, architectural decisions, and engineering discussions — and exposes a hybrid retrieval interface for assembling context.

This spec covers the **initial backend skeleton only**. No AI pipelines, no agents, no graph reasoning, no UI.

---

## 2. Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Web framework | FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 + pgvector |
| Migrations | Alembic |
| Package manager | uv |
| Linting/formatting | Ruff |
| Type checking | MyPy |
| Testing | pytest + pytest-asyncio + testcontainers |
| Containerization | Docker + docker-compose |
| Structured logging | structlog |
| Observability | Request ID middleware (ASGI/BaseHTTPMiddleware) |

---

## 3. Architecture: Vertical Slices + Shared Cognitive Core

The system uses a **modular monolith** architecture. FastAPI stays thin — no business logic in route handlers.

### Core principle

```
schema/  →  pure data (no SQLAlchemy, no behavior)
domain/  →  business rules and normalization logic
infrastructure/  →  ORM, engine, session, repositories, config, observability
behavioral slices (ingestion/, retrieval/, etc.)  →  orchestration via service.py
```

Knowledge representation is separated from persistence. `schema/` describes *what knowledge is*. `infrastructure/db/` describes *how it is stored*. They never mix.

---

## 4. Project Structure

```
(project root)/
├── apps/
│   ├── api/
│   │   ├── main.py              # application factory
│   │   ├── lifespan.py          # startup/shutdown
│   │   └── routes/
│   │       └── v1/
│   │           └── health.py
│   ├── worker/                  # placeholder
│   └── cli/                     # placeholder
│
├── lore/
│   ├── schema/                  # pure cognitive model — NO SQLAlchemy, NO behavior
│   │   ├── source.py            # Source (dataclass), SourceType (str, Enum)
│   │   ├── document.py          # Document, DocumentVersion
│   │   ├── chunk.py             # Chunk (embedding_ref: str | None, not vector)
│   │   └── provenance.py        # Provenance (placeholder)
│   │
│   ├── domain/                  # business rules of knowledge transformation
│   │   └── source.py            # normalize_source_type()
│   │                            # future: entity merging, conflict resolution,
│   │                            # confidence scoring, temporal decay, provenance validation
│   │
│   ├── ingestion/               # behavioral: accepts → normalizes → stores
│   │   └── service.py           # orchestration layer
│   ├── extraction/              # behavioral: semantic extraction (placeholder)
│   │   └── service.py
│   ├── retrieval/               # behavioral: hybrid search (placeholder)
│   │   └── service.py           # intelligence layer: fusion, rerank, hybrid_search
│   ├── graph/                   # behavioral: knowledge graph (placeholder)
│   ├── memory/                  # behavioral: memory management (placeholder)
│   ├── context/                 # behavioral: context assembly (placeholder)
│   ├── freshness/               # behavioral: temporal freshness (placeholder)
│   │
│   └── infrastructure/
│       ├── config.py            # pydantic-settings Settings, get_settings()
│       ├── db/
│       │   ├── engine.py        # async SQLAlchemy engine
│       │   ├── session.py       # AsyncSession factory + FastAPI DI
│       │   ├── base.py          # DeclarativeBase
│       │   ├── models/          # ORM models only — embedding lives here
│       │   │   ├── source.py
│       │   │   ├── document.py
│       │   │   └── chunk.py     # Vector(3072), tsvector
│       │   └── repositories/    # data access layer — only way to touch ORM
│       │       ├── base.py
│       │       ├── source.py
│       │       ├── document.py
│       │       └── chunk.py
│       └── observability/
│           ├── logging.py       # structlog setup (JSON in prod, pretty in dev)
│           └── middleware.py    # RequestIDMiddleware (BaseHTTPMiddleware, MVP)
│
├── tests/
│   ├── unit/                    # no DB, pure logic
│   ├── integration/
│   │   └── conftest.py          # testcontainers postgres:16 + pgvector init
│   └── e2e/
│
├── migrations/                  # Alembic
├── docs/
├── scripts/
├── pyproject.toml
├── Makefile
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── README.md
```

---

## 5. Schema Layer

All schema objects are **frozen dataclasses** or Pydantic models with no SQLAlchemy imports.

### SourceType

```python
class SourceType(str, Enum):
    GIT_REPO = "git_repo"
    MARKDOWN = "markdown"
    ADR = "adr"
    SLACK = "slack"
    CONFLUENCE = "confluence"
    UNKNOWN = "unknown"
```

- Stored as `TEXT` in PostgreSQL (not a DB enum — schema must be stable as new integrations arrive)
- Two DB fields: `source_type_raw` (verbatim input) + `source_type_canonical` (normalized)
- Normalization lives in `domain/source.py`, not in schema

### Source

```python
@dataclass(frozen=True)
class Source:
    id: UUID
    source_type_raw: str
    source_type_canonical: SourceType
    origin: str
    created_at: datetime
    updated_at: datetime
```

### Chunk

```python
@dataclass(frozen=True)
class Chunk:
    id: UUID
    document_version_id: UUID
    text: str
    embedding_ref: str | None   # e.g. "openai:text-embedding-3-large:<sha256>"
    metadata: dict[str, Any]
    created_at: datetime
```

`embedding_ref` is a string reference, not the vector itself. The vector lives exclusively in `infrastructure/db/models/chunk.py` as `Vector(3072)`.

---

## 6. Infrastructure: DB Layer

### ORM Models

`ChunkORM` holds the actual vector and full-text search column:

```python
class ChunkORM(Base):
    __tablename__ = "chunks"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    document_version_id: Mapped[UUID] = mapped_column(ForeignKey(...), index=True)
    text: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector(3072), nullable=True)
    text_search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)"),
    )
    embedding_ref: Mapped[str | None]  # e.g. "openai:text-embedding-3-large:<sha256>"
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    __table_args__ = (
        Index("ix_chunks_embedding", "embedding", postgresql_using="hnsw"),
        Index("ix_chunks_text_search", "text_search", postgresql_using="gin"),
    )
```

### Repository Contract

Repositories are the **only** way to access ORM models. Behavioral slices (`ingestion/`, `retrieval/`) work exclusively with schema objects.

```python
# WRITE PATH (ingestion/extraction)
async def create(self, chunk: Chunk, embedding: list[float] | None) -> Chunk
async def update_embedding(self, chunk_id: UUID, embedding: list[float]) -> None

# READ PATH (retrieval/context assembly — dumb access only)
async def get_by_id(self, id: UUID) -> Chunk | None
async def query_by_vector(self, vec: list[float], limit: int) -> list[Chunk]
async def query_by_text(self, query: str, limit: int) -> list[Chunk]
```

`hybrid_search()`, reranking, and fusion logic live in `retrieval/service.py`, **not** in the repository.

---

## 7. FastAPI Application

### Application Factory

```python
# apps/api/main.py
def create_app() -> FastAPI:
    app = FastAPI(title="Lore", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(v1_router, prefix="/api/v1")
    app.add_exception_handler(LoreError, lore_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app
```

### Health Endpoint

```http
GET /api/v1/health
→ 200 {"status": "ok"}
```

### Session Injection

```python
async def get_session(settings: Settings = Depends(get_settings)) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine) as session:
        yield session
```

---

## 8. Configuration

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    openai_api_key: SecretStr
    log_level: str = "INFO"
    environment: Literal["development", "production"] = "development"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int | None = None  # runtime metadata, not a hard constraint
```

`redis_url` is intentionally absent — Redis is in docker-compose as a future placeholder only. No application code references it.

---

## 9. Error Handling

### Exception Hierarchy

```python
class LoreError(Exception): ...       # base — all controlled errors
class NotFoundError(LoreError): ...
class ValidationError(LoreError): ...
# Future (not implemented in skeleton):
# RetrievalError, IngestionError, EmbeddingError, ConsistencyError, TemporalConflictError
```

### Error Response Format

```json
{"error": {"code": "not_found", "message": "Document not found"}}
```

### Handler Strategy

- `LoreError` → structured JSON response, appropriate 4xx status
- `Exception` → 500 + full structlog error logging; in development, detail is surfaced; never silently swallowed

---

## 10. Observability

- `structlog` for structured logging (JSON in production, colorized in development)
- Every log entry includes: `timestamp`, `level`, `event`, `request_id`
- `RequestIDMiddleware` binds `request_id` to structlog context vars for the duration of each request
- Implementation: `BaseHTTPMiddleware` (acceptable for MVP; candidate for pure ASGI middleware if streaming or performance becomes a concern)

---

## 11. Testing Strategy

### Three-level structure

| Level | Tooling | What it covers |
|---|---|---|
| `tests/unit/` | pytest, no DB | Pure logic: normalization, chunking, scoring, graph algorithms |
| `tests/integration/` | testcontainers, real PostgreSQL | ingestion → storage, vector search, repository contract |
| `tests/e2e/` | TestClient | Full request cycle via FastAPI |

### Integration DB Fixture

```python
@pytest.fixture(scope="session")
async def db_engine():
    with PostgresContainer("postgres:16") as pg:
        # pgvector enabled via init script in scripts/init-pgvector.sql
        engine = create_async_engine(pg.get_connection_url())
        await run_alembic_migrations(engine)  # test utility in tests/integration/conftest.py
        yield engine
```

`run_alembic_migrations` is a helper defined in `tests/integration/conftest.py` that programmatically calls `alembic upgrade head` against the test engine URL.

Using `postgres:16` with a pgvector init script rather than `pgvector/pgvector:pg16` for stability and explicit version control.

### Pytest Markers

```
@pytest.mark.unit          # always fast, no external deps
@pytest.mark.integration   # requires Docker daemon
@pytest.mark.e2e           # optional, nightly in CI
```

### Initial Tests

- `tests/e2e/test_health.py`: `GET /api/v1/health` → `{"status": "ok"}`

---

## 12. Docker Environment

```yaml
services:
  api:
    build: .
    env_file: .env
    depends_on: [postgres]

  postgres:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-pgvector.sql:/docker-entrypoint-initdb.d/init.sql
    env_file: .env

  redis:
    image: redis:7-alpine
    # No application code connects to Redis in v0.1
    # Included as infrastructure placeholder for future task queue / cache
```

---

## 13. Developer Experience

### Makefile Commands

| Command | Action |
|---|---|
| `make dev` | Start docker-compose + run API |
| `make test` | Run all tests |
| `make test-unit` | Run unit tests only |
| `make test-integration` | Run integration tests |
| `make lint` | Ruff check |
| `make format` | Ruff format |
| `make type-check` | MyPy |
| `make migration name=...` | Create Alembic migration |
| `make migrate` | Apply migrations |

### pre-commit hooks

- `ruff check --fix`
- `ruff format`
- `mypy`

---

## 14. Key Architectural Rules (invariants)

1. **Schema never imports SQLAlchemy.** `lore/schema/` contains only Python stdlib + dataclasses/Pydantic.
2. **Behavioral slices never touch ORM directly.** All DB access goes through `infrastructure/db/repositories/`.
3. **Repositories are dumb.** No fusion, ranking, or retrieval intelligence in repositories.
4. **Intelligence lives in service.py.** Each behavioral module has a `service.py` as its orchestration layer.
5. **Domain logic lives in `domain/`.** Normalization, business rules, and knowledge transformation are not in schema or infrastructure.
6. **Embedding vectors are an infrastructure concern.** `schema/chunk.py` holds `embedding_ref: str | None`. The `Vector(3072)` column exists only in `infrastructure/db/models/chunk.py`.
7. **Source type is a soft constraint.** `source_type_raw` preserves the verbatim input. `source_type_canonical` holds the normalized value. The DB column is `TEXT`, not an enum.

---

## 15. Out of Scope (v0.1)

- Advanced AI pipelines and agents
- Graph reasoning
- LangChain or any orchestration framework
- Celery / task queues (Redis present but unused)
- Kubernetes or complex infra
- Authentication
- UI

---

## 16. Future Roadmap (not in scope, for orientation)

- `v0.2`: Ingestion pipeline — chunking strategy, idempotency, provenance tracking
- `v0.3`: Embedding pipeline — OpenAI integration, async embedding jobs
- `v0.4`: Hybrid retrieval — vector + full-text fusion, reranking
- `v0.5`: Knowledge graph — entity extraction, assertion generation
- `v0.6`: Temporal freshness — decay model, staleness detection
- `v1.0`: Context assembly API for AI agents
