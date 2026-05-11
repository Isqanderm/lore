# Connector Architecture

Lore uses a pluggable connector system to ingest data from external providers.

## Layer Model

```
Provider API (GitHub, GitLab, ...)
    ↓
lore/connectors/<provider>/   Provider-specific integration
    ↓ RawExternalObject
lore/ingestion/service.py     Normalizes + persists
    ↓ CanonicalDocumentDraft
lore/schema/                  Canonical knowledge model
    ↓
DB: documents + document_versions
```

## Connector SDK

The SDK (`lore/connector_sdk/`) is the stable contract. Connectors implement `BaseConnector`:

- `inspect_resource(uri)` → `ExternalContainerDraft` — fetch repo metadata
- `full_sync(request)` → `SyncResult` — fetch all raw objects
- `normalize(raw)` → `list[CanonicalDocumentDraft]` — map to canonical model

## Import Rules

| Module | May import |
|---|---|
| `lore/connector_sdk/` | `lore/schema/`, stdlib |
| `lore/connectors/github/` | `lore/connector_sdk/`, `lore/schema/` |
| `lore/ingestion/` | `lore/connector_sdk/`, `lore/infrastructure/`, `lore/schema/` |
| `apps/api/lifespan.py` | All of the above (composition root) |

**Never:** `lore/ingestion/` importing `lore/connectors/github/`

## Data Hashing

- `raw_payload_hash`: `sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str))`
- `content_hash` / `document_versions.checksum`: `sha256(content)`
- Both prefixed with `"sha256:"`

## Provenance

Each `DocumentVersion.metadata` stores a provenance snapshot at creation time:
- `external_id` — stable object identifier
- `external_url` — human URL at this version (with commit SHA for files)
- `raw_payload_hash` — hash of raw provider payload at ingestion time
- `commit_sha` — git commit SHA (mandatory for github.file objects)
- `path` — file path

## Adding a Connector

1. `lore/connectors/<provider>/__init__.py` (empty)
2. `models.py` — provider-specific internal types
3. `auth.py` — auth config, reads from Settings
4. `client.py` — async HTTP client with error mapping to SDK errors
5. `file_policy.py` (if applicable) — selection rules
6. `normalizer.py` — maps object_type → document_kind
7. `manifest.py` — `ConnectorManifest` with honest capabilities
8. `connector.py` — `BaseConnector` subclass
9. Register in `apps/api/lifespan.py`
10. Run `pytest tests/unit/connector_sdk/test_import_boundary.py` to verify isolation
