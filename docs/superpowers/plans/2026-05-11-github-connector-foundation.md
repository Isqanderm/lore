# GitHub Connector Foundation — Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Architect and implement connector SDK + GitHub connector MVP for Lore v0.2.

**Branch:** `worktree-feat+v0.2-github-connector-foundation` → PR to `main`

**Design spec:** `docs/superpowers/specs/2026-05-11-github-connector-design.md`

---

## Plan split into 5 phase files

Implement in order. Each phase is self-contained and ends with working, tested code.

| Phase | File | Tasks | What it builds |
|---|---|---|---|
| 1 | [phase1-sdk.md](2026-05-11-github-connector-phase1-sdk.md) | 1–3 | `lore/connector_sdk/` — BaseConnector, ConnectorRegistry, models, import boundary test |
| 2 | [phase2-storage.md](2026-05-11-github-connector-phase2-storage.md) | 4–7 | Migration 0002, ExternalObject ORM, all repositories |
| 3 | [phase3-github-connector.md](2026-05-11-github-connector-phase3-github-connector.md) | 8–12 | `lore/connectors/github/` — client, file_policy, normalizer, connector |
| 4 | [phase4-ingestion.md](2026-05-11-github-connector-phase4-ingestion.md) | 13–14 | IngestionService (idempotency + provenance), RepositoryImportService |
| 5 | [phase5-wiring-tests.md](2026-05-11-github-connector-phase5-wiring-tests.md) | 15–19 | App wiring, API routes, integration + E2E tests, smoke test, docs |

---

## Execution constraints

These rules apply throughout all phases. Claude must follow them even when the phase plan does not repeat them.

**Before modifying existing files:**
- Read the current file first
- Apply minimal additive changes only — do not replace entire files
- Preserve existing columns, relationships, indexes, helper methods, and repository behaviour

**ORM `metadata` attribute:**
- Never use `metadata` as a Python attribute name on SQLAlchemy ORM models — it shadows `DeclarativeBase.metadata`
- Use `metadata_: Mapped[...] = mapped_column("metadata", JSONB, ...)` in ORM models
- Map `orm.metadata_` → `schema.metadata` in `_orm_to_schema` functions
- Schema dataclasses and the user-facing API keep the name `metadata`

**Provider boundary:**
- Production code outside `apps/api/lifespan.py` must NOT import `lore.connectors.github`
- Unit tests for `IngestionService` must NOT import `GitHubNormalizer` — use `FakeStubConnector` only
- Integration tests may use `GitHubNormalizer` inside fake connectors

**`logical_path` nullability:**
- Never coerce `logical_path = None` to `""` — pass `None` as-is to repository methods
- Repository `get_by_source_kind_path` must query `IS NULL` when `logical_path is None`

**FastAPI routing:**
- Use `APIRouter(prefix="/api/v1")` + `app.include_router(...)` — never mount a nested `FastAPI()` instance
- Inspect `apps/api/main.py` before modifying; preserve middleware and exception handlers

**Error handling in connectors:**
- Catch `ConnectorError` specifically for expected failures (binary files, 404)
- Append skipped-file warnings to `SyncResult.warnings`
- Do not swallow unexpected exceptions with bare `except Exception: continue`

**Testing:**
- Default test suite must not require `GITHUB_TOKEN`
- `POST /repositories/import` API test belongs in `tests/integration/` (needs DB), not `tests/e2e/`
- `GET /connectors` API test is true E2E (no DB required)

---

## Key invariants enforced throughout

1. `lore/connectors/github/` can be deleted — `lore.schema`, `lore.connector_sdk`, `lore.ingestion` imports must not break
2. `GitHubConnector` never creates DB records — only fetches + normalizes
3. `IngestionService` depends on `BaseConnector`, never on `GitHubConnector`
4. Only `apps/api/lifespan.py` imports `lore.connectors.github`
5. `document_versions.checksum` IS `CanonicalDocumentDraft.content_hash` — no duplicate column
6. `raw_payload_hash` = `sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str))`
7. `commit_sha` mandatory in `RawExternalObject.metadata` for file objects
8. All tests hermetic by default; live tests behind `@pytest.mark.live_github`
