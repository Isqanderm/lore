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
