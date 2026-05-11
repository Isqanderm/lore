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
