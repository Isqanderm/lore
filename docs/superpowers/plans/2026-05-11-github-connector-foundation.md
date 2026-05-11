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

## Key invariants enforced throughout

1. `lore/connectors/github/` can be deleted — `lore.schema`, `lore.connector_sdk`, `lore.ingestion` imports must not break
2. `GitHubConnector` never creates DB records — only fetches + normalizes
3. `IngestionService` depends on `BaseConnector`, never on `GitHubConnector`
4. Only `apps/api/lifespan.py` imports `lore.connectors.github`
5. `document_versions.checksum` IS `CanonicalDocumentDraft.content_hash` — no duplicate column
6. `raw_payload_hash` = `sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str))`
7. `commit_sha` mandatory in `RawExternalObject.metadata` for file objects
8. All tests hermetic by default; live tests behind `@pytest.mark.live_github`
