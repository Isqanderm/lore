# Lore Backend Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a production-grade backend skeleton for the Lore AI memory system that boots locally via docker-compose, connects to PostgreSQL with pgvector, runs Alembic migrations, exposes a FastAPI `/api/v1/health` endpoint, and provides a clean, typed foundation for future ingestion and retrieval development.

**Architecture:** Modular monolith with vertical behavioral slices (`ingestion/`, `retrieval/`, etc.) sharing a cognitive model layer (`schema/`) and domain logic layer (`domain/`). All persistence goes through repositories in `infrastructure/db/repositories/`. FastAPI stays thin — no business logic in route handlers.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, PostgreSQL 16 + pgvector, Alembic, pydantic-settings, structlog, uv, Ruff, MyPy, pytest + pytest-asyncio + testcontainers-python

---

## File Map

```
pyproject.toml                              # uv project config, all deps, ruff/mypy config
.env.example                                # all env vars with safe local defaults
.pre-commit-config.yaml                     # ruff + mypy hooks
Makefile                                    # dev commands
Dockerfile                                  # api service image
docker-compose.yml                          # api + postgres + redis
scripts/
  init-pgvector.sql                         # CREATE EXTENSION IF NOT EXISTS vector;

apps/
  __init__.py
  api/
    __init__.py
    main.py                                 # create_app() factory
    lifespan.py                             # startup/shutdown async context manager
    routes/
      __init__.py
      v1/
        __init__.py
        health.py                           # GET /api/v1/health

lore/
  __init__.py
  schema/
    __init__.py
    source.py                               # SourceType enum + Source dataclass
    document.py                             # Document + DocumentVersion dataclasses
    chunk.py                                # Chunk dataclass (embedding_ref, no vector)
    provenance.py                           # Provenance dataclass (placeholder)
    errors.py                               # LoreError, NotFoundError, ValidationError
  domain/
    __init__.py
    source.py                               # normalize_source_type()
  ingestion/
    __init__.py
    service.py                              # IngestionService (placeholder)
  extraction/
    __init__.py
    service.py                              # placeholder
  retrieval/
    __init__.py
    service.py                              # RetrievalService (placeholder)
  graph/
    __init__.py
  memory/
    __init__.py
  context/
    __init__.py
  freshness/
    __init__.py
  infrastructure/
    __init__.py
    config.py                               # Settings (pydantic-settings)
    db/
      __init__.py
      engine.py                             # create_async_engine()
      session.py                            # AsyncSession factory + get_session() DI
      base.py                               # DeclarativeBase
      models/
        __init__.py
        source.py                           # SourceORM
        document.py                         # DocumentORM + DocumentVersionORM
        chunk.py                            # ChunkORM with Vector(3072) + tsvector
      repositories/
        __init__.py
        base.py                             # BaseRepository[T]
        source.py                           # SourceRepository
        document.py                         # DocumentRepository + DocumentVersionRepository
        chunk.py                            # ChunkRepository
    observability/
      __init__.py
      logging.py                            # configure_logging() with structlog
      middleware.py                         # RequestIDMiddleware

migrations/
  env.py                                    # Alembic env (async)
  script.py.mako
  versions/
    0001_initial_schema.py                  # initial migration

tests/
  __init__.py
  conftest.py                               # pytest markers registration
  unit/
    __init__.py
    domain/
      __init__.py
      test_source_normalization.py          # tests for normalize_source_type()
  integration/
    __init__.py
    conftest.py                             # testcontainers PostgreSQL fixture
    test_repositories.py                    # SourceRepository, ChunkRepository
  e2e/
    __init__.py
    conftest.py                             # TestClient fixture
    test_health.py                          # GET /api/v1/health → 200 {"status":"ok"}

docs/
  architecture.md
README.md
```

---

## Task 1: Project Initialization with uv

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`

- [ ] **Step 1: Initialize uv project**

```bash
uv init --no-readme --python 3.12
```

Expected output: `pyproject.toml` created.

- [ ] **Step 2: Replace pyproject.toml with full config**

```toml
[project]
name = "lore"
version = "0.1.0"
description = "AI-native temporal memory and context engine"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "alembic>=1.13.0",
    "asyncpg>=0.29.0",
    "pgvector>=0.3.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "structlog>=24.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "testcontainers[postgres]>=4.0.0",
    "mypy>=1.10.0",
    "ruff>=0.4.0",
    "pre-commit>=3.7.0",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "testcontainers[postgres]>=4.0.0",
    "mypy>=1.10.0",
    "ruff>=0.4.0",
    "pre-commit>=3.7.0",
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "unit: fast tests without DB",
    "integration: tests requiring Docker + PostgreSQL",
    "e2e: end-to-end API tests",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["lore", "apps"]
```

- [ ] **Step 3: Install dependencies**

```bash
uv sync --all-extras
```

Expected output: `.venv` created, all packages installed.

- [ ] **Step 4: Create .python-version**

```
3.12
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .python-version uv.lock
git commit -m "chore: initialize uv project with full dependency manifest"
```

---

## Task 2: Directory Skeleton

**Files:** All `__init__.py` files + empty placeholder modules

- [ ] **Step 1: Create all directories and __init__.py files**

```bash
mkdir -p apps/api/routes/v1
mkdir -p lore/schema lore/domain
mkdir -p lore/ingestion lore/extraction lore/retrieval
mkdir -p lore/graph lore/memory lore/context lore/freshness
mkdir -p lore/infrastructure/db/models lore/infrastructure/db/repositories
mkdir -p lore/infrastructure/observability
mkdir -p migrations/versions
mkdir -p tests/unit/domain tests/integration tests/e2e
mkdir -p scripts docs/superpowers/plans docs/superpowers/specs

touch apps/__init__.py
touch apps/api/__init__.py apps/api/routes/__init__.py apps/api/routes/v1/__init__.py
touch apps/worker/__init__.py apps/cli/__init__.py
touch lore/__init__.py
touch lore/schema/__init__.py lore/domain/__init__.py
touch lore/ingestion/__init__.py lore/extraction/__init__.py
touch lore/retrieval/__init__.py lore/graph/__init__.py
touch lore/memory/__init__.py lore/context/__init__.py lore/freshness/__init__.py
touch lore/infrastructure/__init__.py
touch lore/infrastructure/db/__init__.py
touch lore/infrastructure/db/models/__init__.py
touch lore/infrastructure/db/repositories/__init__.py
touch lore/infrastructure/observability/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py tests/unit/domain/__init__.py
touch tests/integration/__init__.py tests/e2e/__init__.py
```

- [ ] **Step 2: Create placeholder service files**

`lore/ingestion/service.py`:
```python
class IngestionService:
    pass
```

`lore/extraction/service.py`:
```python
class ExtractionService:
    pass
```

`lore/retrieval/service.py`:
```python
class RetrievalService:
    pass
```

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "chore: create project directory skeleton with placeholder modules"
```

---

## Task 3: Configuration System

**Files:**
- Create: `lore/infrastructure/config.py`
- Create: `.env.example`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_config.py`:
```python
import pytest
from lore.infrastructure.config import Settings


def test_settings_has_required_fields() -> None:
    s = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/lore",
        openai_api_key="sk-test",
    )
    assert s.environment == "development"
    assert s.log_level == "INFO"
    assert s.embedding_model == "text-embedding-3-large"
    assert s.embedding_dimensions is None


def test_settings_rejects_invalid_environment() -> None:
    with pytest.raises(Exception):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/lore",
            openai_api_key="sk-test",
            environment="staging",  # not in Literal["development", "production"]
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'lore.infrastructure.config'`

- [ ] **Step 3: Implement Settings**

`lore/infrastructure/config.py`:
```python
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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Create .env.example**

```bash
cat > .env.example << 'EOF'
# Database
DATABASE_URL=postgresql+asyncpg://lore:lore@localhost:5432/lore

# OpenAI (required for future embedding pipeline)
OPENAI_API_KEY=sk-...

# Application
ENVIRONMENT=development
LOG_LEVEL=INFO
EMBEDDING_MODEL=text-embedding-3-large
EOF
```

- [ ] **Step 6: Commit**

```bash
git add lore/infrastructure/config.py .env.example tests/unit/test_config.py
git commit -m "feat: add pydantic-settings configuration system"
```

---

## Task 4: Schema Layer — Source

**Files:**
- Create: `lore/schema/source.py`
- Create: `lore/schema/errors.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_schema_source.py`:
```python
from uuid import uuid4
from datetime import datetime, timezone

from lore.schema.source import Source, SourceType


def test_source_is_frozen() -> None:
    s = Source(
        id=uuid4(),
        source_type_raw="git",
        source_type_canonical=SourceType.GIT_REPO,
        origin="https://github.com/example/repo",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    import pytest
    with pytest.raises(Exception):
        s.origin = "mutated"  # type: ignore[misc]


def test_source_type_values() -> None:
    assert SourceType.GIT_REPO == "git_repo"
    assert SourceType.UNKNOWN == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_schema_source.py -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Implement schema/source.py**

`lore/schema/source.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class SourceType(str, Enum):
    GIT_REPO = "git_repo"
    MARKDOWN = "markdown"
    ADR = "adr"
    SLACK = "slack"
    CONFLUENCE = "confluence"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Source:
    id: UUID
    source_type_raw: str
    source_type_canonical: SourceType
    origin: str
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Implement schema/errors.py**

`lore/schema/errors.py`:
```python
class LoreError(Exception):
    pass


class NotFoundError(LoreError):
    pass


class ValidationError(LoreError):
    pass
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_schema_source.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add lore/schema/source.py lore/schema/errors.py tests/unit/test_schema_source.py
git commit -m "feat: add Source schema with SourceType enum and error hierarchy"
```

---

## Task 5: Schema Layer — Document and Chunk

**Files:**
- Create: `lore/schema/document.py`
- Create: `lore/schema/chunk.py`
- Create: `lore/schema/provenance.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_schema_document.py`:
```python
from uuid import uuid4
from datetime import datetime, timezone
from lore.schema.document import Document, DocumentVersion


def test_document_frozen() -> None:
    import pytest
    doc = Document(
        id=uuid4(),
        source_id=uuid4(),
        title="Architecture Decision Record",
        path="docs/adr/001-database.md",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        doc.title = "mutated"  # type: ignore[misc]


def test_document_version_checksum() -> None:
    dv = DocumentVersion(
        id=uuid4(),
        document_id=uuid4(),
        version=1,
        content="# Hello",
        checksum="sha256:abc123",
        created_at=datetime.now(timezone.utc),
    )
    assert dv.version == 1
    assert dv.checksum.startswith("sha256:")
```

`tests/unit/test_schema_chunk.py`:
```python
from uuid import uuid4
from datetime import datetime, timezone
from lore.schema.chunk import Chunk


def test_chunk_without_embedding_ref() -> None:
    chunk = Chunk(
        id=uuid4(),
        document_version_id=uuid4(),
        text="The system uses PostgreSQL as primary store.",
        embedding_ref=None,
        metadata={},
        created_at=datetime.now(timezone.utc),
    )
    assert chunk.embedding_ref is None


def test_chunk_with_embedding_ref() -> None:
    chunk = Chunk(
        id=uuid4(),
        document_version_id=uuid4(),
        text="example",
        embedding_ref="openai:text-embedding-3-large:v1:abc123",
        metadata={"source": "adr"},
        created_at=datetime.now(timezone.utc),
    )
    parts = chunk.embedding_ref.split(":")
    assert len(parts) == 4
    assert parts[0] == "openai"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_schema_document.py tests/unit/test_schema_chunk.py -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Implement document.py and chunk.py**

`lore/schema/document.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Document:
    id: UUID
    source_id: UUID
    title: str
    path: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentVersion:
    id: UUID
    document_id: UUID
    version: int
    content: str
    checksum: str
    created_at: datetime
```

`lore/schema/chunk.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Chunk:
    id: UUID
    document_version_id: UUID
    text: str
    embedding_ref: str | None
    metadata: dict[str, Any]
    created_at: datetime
```

`lore/schema/provenance.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Provenance:
    """Tracks the origin and transformation history of a knowledge artifact."""
    id: UUID
    entity_id: UUID
    source_id: UUID
    created_at: datetime
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_schema_document.py tests/unit/test_schema_chunk.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add lore/schema/document.py lore/schema/chunk.py lore/schema/provenance.py \
  tests/unit/test_schema_document.py tests/unit/test_schema_chunk.py
git commit -m "feat: add Document, DocumentVersion, Chunk, Provenance schema types"
```

---

## Task 6: Domain Layer — Source Normalization

**Files:**
- Create: `lore/domain/source.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/domain/test_source_normalization.py`:
```python
import pytest
from lore.domain.source import normalize_source_type
from lore.schema.source import SourceType


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("git_repo", SourceType.GIT_REPO),
    ("git", SourceType.GIT_REPO),
    ("github", SourceType.GIT_REPO),
    ("gitlab", SourceType.GIT_REPO),
    ("markdown", SourceType.MARKDOWN),
    ("md", SourceType.MARKDOWN),
    ("adr", SourceType.ADR),
    ("architectural_decision", SourceType.ADR),
    ("slack", SourceType.SLACK),
    ("confluence", SourceType.CONFLUENCE),
    ("wiki", SourceType.CONFLUENCE),
    ("totally_unknown_source", SourceType.UNKNOWN),
    ("", SourceType.UNKNOWN),
    ("  GIT  ", SourceType.GIT_REPO),  # whitespace + case insensitive
])
def test_normalize_source_type(raw: str, expected: SourceType) -> None:
    assert normalize_source_type(raw) == expected
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/domain/test_source_normalization.py -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Implement normalize_source_type**

`lore/domain/source.py`:
```python
from lore.schema.source import SourceType

_CANONICAL_MAP: dict[str, SourceType] = {
    "git_repo": SourceType.GIT_REPO,
    "git": SourceType.GIT_REPO,
    "github": SourceType.GIT_REPO,
    "gitlab": SourceType.GIT_REPO,
    "bitbucket": SourceType.GIT_REPO,
    "markdown": SourceType.MARKDOWN,
    "md": SourceType.MARKDOWN,
    "adr": SourceType.ADR,
    "architectural_decision": SourceType.ADR,
    "architectural_decision_record": SourceType.ADR,
    "slack": SourceType.SLACK,
    "confluence": SourceType.CONFLUENCE,
    "wiki": SourceType.CONFLUENCE,
}


def normalize_source_type(raw: str) -> SourceType:
    return _CANONICAL_MAP.get(raw.strip().lower(), SourceType.UNKNOWN)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/domain/test_source_normalization.py -v
```

Expected: `PASSED` (14 parametrized cases)

- [ ] **Step 5: Commit**

```bash
git add lore/domain/source.py tests/unit/domain/test_source_normalization.py
git commit -m "feat: add domain normalize_source_type with canonical mapping"
```

---

## Task 7: Observability — Logging and Middleware

**Files:**
- Create: `lore/infrastructure/observability/logging.py`
- Create: `lore/infrastructure/observability/middleware.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_observability.py`:
```python
import structlog
from lore.infrastructure.observability.logging import configure_logging


def test_configure_logging_does_not_raise() -> None:
    configure_logging(log_level="DEBUG", environment="development")


def test_configure_logging_production_does_not_raise() -> None:
    configure_logging(log_level="INFO", environment="production")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_observability.py -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Implement configure_logging**

`lore/infrastructure/observability/logging.py`:
```python
import logging
import sys
from typing import Literal

import structlog


def configure_logging(
    log_level: str = "INFO",
    environment: Literal["development", "production"] = "development",
) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if environment == "production":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(log_level.upper())
```

- [ ] **Step 4: Implement RequestIDMiddleware**

`lore/infrastructure/observability/middleware.py`:
```python
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response: Response = await super().dispatch(request, call_next)  # type: ignore[arg-type]
            response.headers["X-Request-ID"] = request_id
            return response

    async def call_next(self, request: Request) -> Response:  # type: ignore[override]
        return await super().call_next(request)  # type: ignore[misc]
```

Wait — `BaseHTTPMiddleware` provides `call_next` via the `dispatch` signature directly. Let me correct:

`lore/infrastructure/observability/middleware.py`:
```python
from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_observability.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add lore/infrastructure/observability/logging.py \
  lore/infrastructure/observability/middleware.py \
  tests/unit/test_observability.py
git commit -m "feat: add structlog logging configuration and RequestIDMiddleware"
```

---

## Task 8: Database Infrastructure — Engine, Session, Base

**Files:**
- Create: `lore/infrastructure/db/base.py`
- Create: `lore/infrastructure/db/engine.py`
- Create: `lore/infrastructure/db/session.py`

- [ ] **Step 1: Implement base.py**

`lore/infrastructure/db/base.py`:
```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: Implement engine.py**

`lore/infrastructure/db/engine.py`:
```python
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from lore.infrastructure.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        str(settings.database_url),
        echo=settings.environment == "development",
        pool_pre_ping=True,
    )
```

- [ ] **Step 3: Implement session.py**

`lore/infrastructure/db/session.py`:
```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, AsyncEngine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
```

- [ ] **Step 4: Write a quick smoke test (no DB required)**

`tests/unit/test_db_infrastructure.py`:
```python
from lore.infrastructure.db.base import Base
from lore.infrastructure.db.engine import build_engine
from lore.infrastructure.config import Settings


def test_base_has_metadata() -> None:
    assert Base.metadata is not None


def test_build_engine_returns_engine() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/lore",
        openai_api_key="sk-test",
    )
    engine = build_engine(settings)
    assert engine is not None
    # Don't actually connect — just verify the engine is constructed
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_db_infrastructure.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add lore/infrastructure/db/base.py lore/infrastructure/db/engine.py \
  lore/infrastructure/db/session.py tests/unit/test_db_infrastructure.py
git commit -m "feat: add async SQLAlchemy engine, session factory, and DeclarativeBase"
```

---

## Task 9: ORM Models

**Files:**
- Create: `lore/infrastructure/db/models/source.py`
- Create: `lore/infrastructure/db/models/document.py`
- Create: `lore/infrastructure/db/models/chunk.py`

- [ ] **Step 1: Install pgvector SQLAlchemy type (already in deps). Verify import:**

```bash
uv run python -c "from pgvector.sqlalchemy import Vector; print('ok')"
```

Expected: `ok`

- [ ] **Step 2: Implement SourceORM**

`lore/infrastructure/db/models/source.py`:
```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, text
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class SourceORM(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_type_raw: Mapped[str] = mapped_column(nullable=False)
    source_type_canonical: Mapped[str] = mapped_column(nullable=False, index=True)
    origin: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 3: Implement DocumentORM and DocumentVersionORM**

`lore/infrastructure/db/models/document.py`:
```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(nullable=False)
    path: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentVersionORM(Base):
    __tablename__ = "document_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
```

- [ ] **Step 4: Implement ChunkORM with Vector and tsvector**

`lore/infrastructure/db/models/chunk.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ChunkORM(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
    embedding_ref: Mapped[str | None] = mapped_column(nullable=True)
    text_search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_chunks_embedding", "embedding", postgresql_using="hnsw"),
        Index("ix_chunks_text_search", "text_search", postgresql_using="gin"),
    )
```

- [ ] **Step 5: Write smoke test for ORM model metadata**

`tests/unit/test_orm_models.py`:
```python
from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.chunk import ChunkORM


def test_source_orm_table_name() -> None:
    assert SourceORM.__tablename__ == "sources"


def test_document_orm_table_name() -> None:
    assert DocumentORM.__tablename__ == "documents"


def test_document_version_orm_table_name() -> None:
    assert DocumentVersionORM.__tablename__ == "document_versions"


def test_chunk_orm_table_name() -> None:
    assert ChunkORM.__tablename__ == "chunks"


def test_chunk_has_embedding_column() -> None:
    cols = {c.name for c in ChunkORM.__table__.columns}
    assert "embedding" in cols
    assert "embedding_ref" in cols
    assert "text_search" in cols
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/test_orm_models.py -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add lore/infrastructure/db/models/ tests/unit/test_orm_models.py
git commit -m "feat: add ORM models for Source, Document, DocumentVersion, Chunk with pgvector"
```

---

## Task 10: Alembic Setup and Initial Migration

**Files:**
- Create: `alembic.ini`
- Modify: `migrations/env.py`
- Create: `migrations/versions/0001_initial_schema.py`
- Create: `scripts/init-pgvector.sql`

- [ ] **Step 1: Initialize Alembic**

```bash
uv run alembic init migrations
```

This creates `alembic.ini` and `migrations/env.py`. We'll overwrite both.

- [ ] **Step 2: Update alembic.ini**

In `alembic.ini`, find `sqlalchemy.url` and comment it out (we'll use env var):

```ini
# sqlalchemy.url = driver://user:pass@localhost/dbname
```

- [ ] **Step 3: Replace migrations/env.py**

`migrations/env.py`:
```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from lore.infrastructure.config import get_settings
from lore.infrastructure.db.base import Base

# Import all ORM models so Alembic detects them via Base.metadata
from lore.infrastructure.db.models import source, document, chunk  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    settings = get_settings()
    context.configure(
        url=str(settings.database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)  # type: ignore[arg-type]
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = get_settings()
    connectable = create_async_engine(str(settings.database_url))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Create pgvector init script**

`scripts/init-pgvector.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

- [ ] **Step 5: Generate initial migration**

First create a `.env` file with a local database URL (can be dummy for autogenerate):

```bash
cp .env.example .env
# Edit .env to set DATABASE_URL pointing to your local postgres if available,
# or use the docker-compose postgres (start it first with: docker compose up postgres -d)
```

If docker-compose postgres is running:
```bash
uv run alembic revision --autogenerate -m "initial_schema"
```

If not, create the migration manually as shown in Step 6.

- [ ] **Step 6: Verify or create migration manually**

The generated file will be in `migrations/versions/`. Rename it to start with `0001_`:

```bash
mv migrations/versions/*initial_schema.py migrations/versions/0001_initial_schema.py
```

Verify it contains `CREATE TABLE` statements for `sources`, `documents`, `document_versions`, `chunks`, the `vector` extension usage, hnsw index, and gin index.

If autogenerate isn't available (no running DB), create manually:

`migrations/versions/0001_initial_schema.py`:
```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_type_raw", sa.Text(), nullable=False),
        sa.Column("source_type_canonical", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sources_source_type_canonical", "sources", ["source_type_canonical"])

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_source_id", "documents", ["source_id"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(3072), nullable=True),
        sa.Column("embedding_ref", sa.Text(), nullable=True),
        sa.Column(
            "text_search",
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_document_version_id", "chunks", ["document_version_id"])
    op.create_index("ix_chunks_embedding", "chunks", ["embedding"], postgresql_using="hnsw")
    op.create_index("ix_chunks_text_search", "chunks", ["text_search"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("sources")
```

- [ ] **Step 7: Commit**

```bash
git add alembic.ini migrations/ scripts/init-pgvector.sql
git commit -m "feat: add Alembic setup with initial schema migration (sources, documents, chunks)"
```

---

## Task 11: Repositories

**Files:**
- Create: `lore/infrastructure/db/repositories/base.py`
- Create: `lore/infrastructure/db/repositories/source.py`
- Create: `lore/infrastructure/db/repositories/document.py`
- Create: `lore/infrastructure/db/repositories/chunk.py`

- [ ] **Step 1: Implement BaseRepository**

`lore/infrastructure/db/repositories/base.py`:
```python
from typing import Generic, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
```

- [ ] **Step 2: Implement SourceRepository**

`lore/infrastructure/db/repositories/source.py`:
```python
from uuid import UUID

from sqlalchemy import select

from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.source import Source, SourceType


def _orm_to_schema(orm: SourceORM) -> Source:
    return Source(
        id=orm.id,
        source_type_raw=orm.source_type_raw,
        source_type_canonical=SourceType(orm.source_type_canonical),
        origin=orm.origin,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SourceRepository(BaseRepository[SourceORM]):
    async def create(self, source: Source) -> Source:
        orm = SourceORM(
            id=source.id,
            source_type_raw=source.source_type_raw,
            source_type_canonical=source.source_type_canonical.value,
            origin=source.origin,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> Source | None:
        result = await self.session.execute(select(SourceORM).where(SourceORM.id == id))
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
```

- [ ] **Step 3: Implement DocumentRepository**

`lore/infrastructure/db/repositories/document.py`:
```python
from uuid import UUID

from sqlalchemy import select

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.document import Document, DocumentVersion


def _doc_orm_to_schema(orm: DocumentORM) -> Document:
    return Document(
        id=orm.id,
        source_id=orm.source_id,
        title=orm.title,
        path=orm.path,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _dv_orm_to_schema(orm: DocumentVersionORM) -> DocumentVersion:
    return DocumentVersion(
        id=orm.id,
        document_id=orm.document_id,
        version=orm.version,
        content=orm.content,
        checksum=orm.checksum,
        created_at=orm.created_at,
    )


class DocumentRepository(BaseRepository[DocumentORM]):
    async def create(self, doc: Document) -> Document:
        orm = DocumentORM(
            id=doc.id,
            source_id=doc.source_id,
            title=doc.title,
            path=doc.path,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _doc_orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> Document | None:
        result = await self.session.execute(select(DocumentORM).where(DocumentORM.id == id))
        orm = result.scalar_one_or_none()
        return _doc_orm_to_schema(orm) if orm else None


class DocumentVersionRepository(BaseRepository[DocumentVersionORM]):
    async def create(self, dv: DocumentVersion) -> DocumentVersion:
        orm = DocumentVersionORM(
            id=dv.id,
            document_id=dv.document_id,
            version=dv.version,
            content=dv.content,
            checksum=dv.checksum,
            created_at=dv.created_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _dv_orm_to_schema(orm)
```

- [ ] **Step 4: Implement ChunkRepository**

`lore/infrastructure/db/repositories/chunk.py`:
```python
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from lore.infrastructure.db.models.chunk import ChunkORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.chunk import Chunk


def _orm_to_schema(orm: ChunkORM) -> Chunk:
    return Chunk(
        id=orm.id,
        document_version_id=orm.document_version_id,
        text=orm.text,
        embedding_ref=orm.embedding_ref,
        metadata=orm.metadata_json or {},
        created_at=orm.created_at,
    )


class ChunkRepository(BaseRepository[ChunkORM]):
    async def create(self, chunk: Chunk, embedding: list[float] | None = None) -> Chunk:
        orm = ChunkORM(
            id=chunk.id,
            document_version_id=chunk.document_version_id,
            text=chunk.text,
            embedding=embedding,
            embedding_ref=chunk.embedding_ref,
            metadata_json=chunk.metadata,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> Chunk | None:
        result = await self.session.execute(select(ChunkORM).where(ChunkORM.id == id))
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None

    async def update_embedding(
        self, chunk_id: UUID, embedding: list[float], embedding_ref: str
    ) -> None:
        result = await self.session.execute(select(ChunkORM).where(ChunkORM.id == chunk_id))
        orm = result.scalar_one_or_none()
        if orm is not None:
            orm.embedding = embedding
            orm.embedding_ref = embedding_ref
            await self.session.flush()

    async def query_by_vector(self, vec: list[float], limit: int = 10) -> list[Chunk]:
        result = await self.session.execute(
            select(ChunkORM)
            .where(ChunkORM.embedding.is_not(None))
            .order_by(ChunkORM.embedding.l2_distance(vec))
            .limit(limit)
        )
        return [_orm_to_schema(row) for row in result.scalars().all()]

    async def query_by_text(self, query: str, limit: int = 10) -> list[Chunk]:
        result = await self.session.execute(
            select(ChunkORM)
            .where(
                ChunkORM.text_search.op("@@")(
                    text("plainto_tsquery('english', :q)").bindparams(q=query)
                )
            )
            .limit(limit)
        )
        return [_orm_to_schema(row) for row in result.scalars().all()]
```

- [ ] **Step 5: Write unit smoke test (no DB)**

`tests/unit/test_repositories_structure.py`:
```python
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.infrastructure.db.repositories.chunk import ChunkRepository


def test_source_repository_inherits_base() -> None:
    assert issubclass(SourceRepository, BaseRepository)


def test_chunk_repository_inherits_base() -> None:
    assert issubclass(ChunkRepository, BaseRepository)
```

- [ ] **Step 6: Run unit test**

```bash
uv run pytest tests/unit/test_repositories_structure.py -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add lore/infrastructure/db/repositories/ tests/unit/test_repositories_structure.py
git commit -m "feat: add repository layer with schema↔ORM mapping for Source, Document, Chunk"
```

---

## Task 12: Error Handlers

**Files:**
- Create: `apps/api/exception_handlers.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_exception_handlers.py`:
```python
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from lore.schema.errors import LoreError, NotFoundError
from apps.api.exception_handlers import lore_exception_handler, unhandled_exception_handler


@pytest.mark.asyncio
async def test_not_found_error_returns_404() -> None:
    app = FastAPI()
    app.add_exception_handler(LoreError, lore_exception_handler)

    @app.get("/test")
    async def route() -> dict[str, str]:
        raise NotFoundError("thing not found")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "thing not found"}}


@pytest.mark.asyncio
async def test_lore_error_returns_400() -> None:
    app = FastAPI()
    app.add_exception_handler(LoreError, lore_exception_handler)

    @app.get("/test")
    async def route() -> dict[str, str]:
        raise LoreError("bad input")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "lore_error"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_exception_handlers.py -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Implement exception handlers**

`apps/api/exception_handlers.py`:
```python
import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from lore.schema.errors import LoreError, NotFoundError, ValidationError

logger = structlog.get_logger(__name__)

_STATUS_MAP: dict[type[LoreError], int] = {
    NotFoundError: 404,
    ValidationError: 422,
}

_CODE_MAP: dict[type[LoreError], str] = {
    NotFoundError: "not_found",
    ValidationError: "validation_error",
}


async def lore_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LoreError)
    status_code = _STATUS_MAP.get(type(exc), 400)
    code = _CODE_MAP.get(type(exc), "lore_error")
    logger.warning("lore.error", code=code, message=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": str(exc)}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("lore.unhandled_error", path=request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Unexpected server error"}},
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_exception_handlers.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add apps/api/exception_handlers.py tests/unit/test_exception_handlers.py
git commit -m "feat: add centralized exception handlers with structured error format"
```

---

## Task 13: FastAPI Application Factory

**Files:**
- Create: `apps/api/lifespan.py`
- Create: `apps/api/routes/v1/health.py`
- Create: `apps/api/main.py`

- [ ] **Step 1: Implement lifespan**

`apps/api/lifespan.py`:
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("lore.startup")
    yield
    logger.info("lore.shutdown")
```

- [ ] **Step 2: Implement health route**

`apps/api/routes/v1/health.py`:
```python
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
```

- [ ] **Step 3: Implement application factory**

`apps/api/main.py`:
```python
from fastapi import FastAPI

from apps.api.exception_handlers import lore_exception_handler, unhandled_exception_handler
from apps.api.lifespan import lifespan
from apps.api.routes.v1.health import router as health_router
from lore.infrastructure.config import get_settings
from lore.infrastructure.observability.logging import configure_logging
from lore.infrastructure.observability.middleware import RequestIDMiddleware
from lore.schema.errors import LoreError

v1_router = FastAPI()
v1_router.include_router(health_router)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, environment=settings.environment)

    app = FastAPI(title="Lore", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.mount("/api/v1", v1_router)
    app.add_exception_handler(LoreError, lore_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


app = create_app()
```

- [ ] **Step 4: Write e2e health test**

`tests/e2e/conftest.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport

from apps.api.main import create_app


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

`tests/e2e/test_health.py`:
```python
import pytest
from httpx import AsyncClient


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_health_response_has_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert "x-request-id" in response.headers


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_health_accepts_custom_request_id(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health", headers={"X-Request-ID": "test-id-123"}
    )
    assert response.headers["x-request-id"] == "test-id-123"
```

- [ ] **Step 5: Create .env for test run**

```bash
cp .env.example .env
# Set at minimum:
# DATABASE_URL=postgresql+asyncpg://lore:lore@localhost:5432/lore
# OPENAI_API_KEY=sk-test
```

- [ ] **Step 6: Run e2e tests**

```bash
uv run pytest tests/e2e/test_health.py -v -m e2e
```

Expected: 3 tests `PASSED`

- [ ] **Step 7: Commit**

```bash
git add apps/api/lifespan.py apps/api/routes/ apps/api/main.py \
  tests/e2e/conftest.py tests/e2e/test_health.py
git commit -m "feat: add FastAPI application factory with health endpoint and request ID middleware"
```

---

## Task 14: Integration Test Setup (testcontainers)

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_source_repository.py`

- [ ] **Step 1: Create root conftest with markers**

`tests/conftest.py`:
```python
import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: fast tests without external dependencies")
    config.addinivalue_line("markers", "integration: tests requiring Docker + PostgreSQL")
    config.addinivalue_line("markers", "e2e: end-to-end API tests")
```

- [ ] **Step 2: Create integration conftest with testcontainers**

`tests/integration/conftest.py`:
```python
from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from lore.infrastructure.db.base import Base
from lore.infrastructure.db.models import source, document, chunk  # noqa: F401


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        engine = create_async_engine(url, echo=False)

        # Enable pgvector extension
        async with engine.begin() as conn:
            await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Run all ORM migrations via create_all (simpler than alembic for test isolation)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield engine
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()  # isolate each test
```

- [ ] **Step 3: Write integration test for SourceRepository**

`tests/integration/test_source_repository.py`:
```python
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.repositories.source import SourceRepository
from lore.schema.source import Source, SourceType


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_and_get_source(db_session: AsyncSession) -> None:
    repo = SourceRepository(db_session)
    source = Source(
        id=uuid4(),
        source_type_raw="github",
        source_type_canonical=SourceType.GIT_REPO,
        origin="https://github.com/example/lore",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    created = await repo.create(source)
    assert created.id == source.id
    assert created.source_type_canonical == SourceType.GIT_REPO

    fetched = await repo.get_by_id(source.id)
    assert fetched is not None
    assert fetched.origin == "https://github.com/example/lore"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_nonexistent_source_returns_none(db_session: AsyncSession) -> None:
    repo = SourceRepository(db_session)
    result = await repo.get_by_id(uuid4())
    assert result is None
```

- [ ] **Step 4: Run integration tests (requires Docker)**

```bash
uv run pytest tests/integration/ -v -m integration
```

Expected: `PASSED` (testcontainers spins up postgres:16, runs create_all, executes tests)

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/integration/conftest.py \
  tests/integration/test_source_repository.py
git commit -m "feat: add testcontainers integration test setup with SourceRepository test"
```

---

## Task 15: Docker Environment

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create Dockerfile**

`Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY . .

CMD ["uv", "run", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create docker-compose.yml**

`docker-compose.yml`:
```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - .:/app

  postgres:
    image: postgres:16
    env_file: .env
    environment:
      POSTGRES_USER: lore
      POSTGRES_PASSWORD: lore
      POSTGRES_DB: lore
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-pgvector.sql:/docker-entrypoint-initdb.d/01-pgvector.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lore"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    # No application code connects to Redis in v0.1
    # Included as infrastructure placeholder

volumes:
  postgres_data:
```

- [ ] **Step 3: Update .env.example with docker-compose defaults**

```bash
cat > .env.example << 'EOF'
# PostgreSQL (matches docker-compose defaults)
DATABASE_URL=postgresql+asyncpg://lore:lore@localhost:5432/lore
POSTGRES_USER=lore
POSTGRES_PASSWORD=lore
POSTGRES_DB=lore

# OpenAI
OPENAI_API_KEY=sk-...

# Application
ENVIRONMENT=development
LOG_LEVEL=INFO
EMBEDDING_MODEL=text-embedding-3-large
EOF
```

- [ ] **Step 4: Verify docker-compose builds**

```bash
docker compose build
```

Expected: Build completes without error.

- [ ] **Step 5: Smoke test the running stack**

```bash
docker compose up -d
sleep 5
curl http://localhost:8000/api/v1/health
```

Expected: `{"status":"ok"}`

```bash
docker compose down
```

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example
git commit -m "feat: add Docker and docker-compose environment with postgres:16 + pgvector"
```

---

## Task 16: Developer Tooling

**Files:**
- Create: `Makefile`
- Create: `.pre-commit-config.yaml`
- Create: `.gitignore`

- [ ] **Step 1: Create Makefile**

`Makefile`:
```makefile
.PHONY: dev test test-unit test-integration test-e2e lint format type-check migrate migration

dev:
	docker compose up -d postgres redis
	uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest tests/ -v

test-unit:
	uv run pytest tests/unit/ -v -m unit

test-integration:
	uv run pytest tests/integration/ -v -m integration

test-e2e:
	uv run pytest tests/e2e/ -v -m e2e

lint:
	uv run ruff check .

format:
	uv run ruff format .

type-check:
	uv run mypy lore/ apps/

migrate:
	uv run alembic upgrade head

migration:
	uv run alembic revision --autogenerate -m "$(name)"
```

- [ ] **Step 2: Create .pre-commit-config.yaml**

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies:
          - pydantic>=2.0.0
          - sqlalchemy[mypy]>=2.0.0
```

- [ ] **Step 3: Create .gitignore**

`.gitignore`:
```
.venv/
__pycache__/
*.py[cod]
.env
*.egg-info/
dist/
.mypy_cache/
.ruff_cache/
.pytest_cache/
```

- [ ] **Step 4: Install pre-commit hooks**

```bash
uv run pre-commit install
```

- [ ] **Step 5: Run lint and type-check**

```bash
make lint
make type-check
```

Expected: No errors (or only minor type stubs warnings).

- [ ] **Step 6: Commit**

```bash
git add Makefile .pre-commit-config.yaml .gitignore
git commit -m "chore: add Makefile, pre-commit hooks, gitignore"
```

---

## Task 17: Documentation

**Files:**
- Create: `README.md`
- Create: `docs/architecture.md`

- [ ] **Step 1: Create README.md**

`README.md`:
```markdown
# Lore

AI-native temporal memory and context engine for agents working with code repositories, documentation, architectural decisions, and engineering discussions.

## Vision

Lore is not a chatbot. It is not a vector database wrapper. It is a **semantic memory substrate** — a system that ingests knowledge, tracks its provenance and temporal evolution, and assembles context for AI agents on demand.

## Quick Start

```bash
cp .env.example .env
# Edit .env: set OPENAI_API_KEY

docker compose up -d
make migrate
curl http://localhost:8000/api/v1/health
# → {"status": "ok"}
```

## Development

```bash
# Install dependencies
uv sync --all-extras

# Start postgres locally
make dev

# Run tests
make test-unit          # fast, no Docker required
make test-integration   # requires Docker
make test-e2e           # full API tests

# Code quality
make lint
make format
make type-check
```

## Stack

| Concern | Technology |
|---|---|
| Language | Python 3.12 |
| Web | FastAPI |
| ORM | SQLAlchemy 2.0 async |
| Database | PostgreSQL 16 + pgvector |
| Migrations | Alembic |
| Logging | structlog |
| Packaging | uv |

## Architecture Overview

```
schema/         Pure cognitive model — what knowledge is
domain/         Business rules — how knowledge transforms
infrastructure/ Persistence, config, observability
ingestion/      Behavioral: ingest → normalize → store
retrieval/      Behavioral: hybrid vector + full-text search
graph/          Behavioral: knowledge graph (v0.5)
context/        Behavioral: context assembly for agents (v1.0)
```

See `docs/architecture.md` for the full design.

## Roadmap

- `v0.1` ← **you are here**: backend skeleton, DB schema, FastAPI foundation
- `v0.2`: Ingestion pipeline — chunking, idempotency, provenance
- `v0.3`: Embedding pipeline — async OpenAI integration
- `v0.4`: Hybrid retrieval — vector + FTS fusion
- `v0.5`: Knowledge graph — entity and assertion extraction
- `v1.0`: Context assembly API for AI agents
```

- [ ] **Step 2: Create docs/architecture.md**

`docs/architecture.md`:
```markdown
# Lore — Architecture

## Memory Layers

Lore organizes knowledge in four layers:

1. **Raw Layer** — verbatim ingested content (source_type_raw, original text)
2. **Canonical Layer** — normalized and classified knowledge (source_type_canonical, chunks)
3. **Semantic Layer** — embedded representations (Vector(3072) in pgvector)
4. **Graph Layer** — entities, assertions, relations (v0.5+)

## Ingestion Pipeline (v0.2+)

```
External source → IngestionService
  → normalize_source_type() [domain]
  → chunk text [domain]
  → store Source, Document, DocumentVersion, Chunk [repository]
  → enqueue embedding job [worker, v0.3]
```

Idempotency is enforced via document path + checksum. Re-ingesting the same content produces no duplicate.

## Retrieval Pipeline (v0.4+)

```
Agent query → RetrievalService
  → embed query [infrastructure/openai]
  → ChunkRepository.query_by_vector()   [semantic search]
  → ChunkRepository.query_by_text()     [full-text search]
  → fuse + rerank results               [retrieval/service.py]
  → assemble context                    [context/service.py]
```

## Temporal Memory

Every `DocumentVersion` is immutable. Ingesting an updated document creates a new version, preserving the full history. The `freshness/` module (v0.6) will compute temporal decay — older knowledge loses relevance weight over time unless explicitly reinforced.

## Provenance Model

Every `Chunk` traces back to: `DocumentVersion → Document → Source`. Future `Assertion` objects will carry multi-hop provenance — knowing not just where a fact came from, but through which transformations it passed.

## Key Invariants

1. `schema/` never imports SQLAlchemy — it describes knowledge, not storage.
2. `domain/` defines transformations, never data structures.
3. Repositories are the only path to ORM models.
4. Embedding vectors live exclusively in `infrastructure/db/models/chunk.py`.
5. Hybrid retrieval intelligence lives in `retrieval/service.py`, not in repositories.
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/architecture.md
git commit -m "docs: add README with setup guide and architecture.md with system design"
```

---

## Task 18: Full Test Run and Verification

- [ ] **Step 1: Run all unit tests**

```bash
make test-unit
```

Expected: All unit tests `PASSED`. Verify the following test files exist and pass:
- `tests/unit/test_config.py`
- `tests/unit/test_schema_source.py`
- `tests/unit/test_schema_document.py`
- `tests/unit/test_schema_chunk.py`
- `tests/unit/test_db_infrastructure.py`
- `tests/unit/test_orm_models.py`
- `tests/unit/test_observability.py`
- `tests/unit/test_exception_handlers.py`
- `tests/unit/test_repositories_structure.py`
- `tests/unit/domain/test_source_normalization.py`

- [ ] **Step 2: Run e2e tests**

```bash
make test-e2e
```

Expected: `tests/e2e/test_health.py` — 3 tests `PASSED`

- [ ] **Step 3: Run integration tests (requires Docker)**

```bash
make test-integration
```

Expected: `tests/integration/test_source_repository.py` — 2 tests `PASSED`

- [ ] **Step 4: Run linting**

```bash
make lint
```

Expected: No errors.

- [ ] **Step 5: Run type check**

```bash
make type-check
```

Expected: No errors (or only known mypy limitations with sqlalchemy generics).

- [ ] **Step 6: Boot the full stack via docker-compose**

```bash
docker compose up -d
sleep 5
make migrate
curl http://localhost:8000/api/v1/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 7: Final commit**

```bash
git add .
git commit -m "chore: v0.1 backend skeleton complete — all tests passing"
```

---

## Self-Review

### Spec coverage check

| Spec Section | Task |
|---|---|
| 1. Project init with uv | Task 1 |
| 2. Tech stack | Task 1 (pyproject.toml) |
| 3. Architecture principle | Tasks 4–11 (layer separation enforced) |
| 4. Project structure | Task 2 |
| 5. Schema layer (Source, Document, Chunk, Provenance) | Tasks 4, 5 |
| 6. ORM + repositories | Tasks 9, 11 |
| 7. FastAPI application factory + health | Task 13 |
| 8. Configuration (pydantic-settings) | Task 3 |
| 9. Error handling | Task 12 |
| 10. Observability (structlog + middleware) | Task 7 |
| 11. Testing setup (unit/integration/e2e) | Tasks 6, 14, 13 |
| 12. Docker environment | Task 15 |
| 13. Developer tooling (Makefile, pre-commit) | Task 16 |
| 14. Documentation (README, architecture.md) | Task 17 |

All 14 spec sections are covered.

### Invariants enforced in the plan

- `schema/` files import only stdlib — no SQLAlchemy ✓
- `domain/source.py` contains only the `normalize_source_type` function, no dataclasses ✓
- Repositories map schema ↔ ORM in both directions (`_orm_to_schema` functions) ✓
- `hybrid_search` is NOT in `ChunkRepository` — left to `retrieval/service.py` ✓
- `embedding_ref` format documented as `"provider:model:version:hash"` ✓
- `embedding_dimensions` in Settings is `int | None` (not hard-coded) ✓
- `redis_url` absent from Settings ✓

### Type consistency

- `Source` dataclass fields match `SourceRepository.create()` parameter and `_orm_to_schema()` output ✓
- `Chunk` dataclass fields match `ChunkRepository.create()` and `_orm_to_schema()` ✓
- `SourceType` imported from `lore.schema.source` everywhere ✓
