"""DocumentVersion.metadata must contain provenance snapshot."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from lore.connector_sdk.models import RawExternalObject, SyncResult
from lore.ingestion.service import IngestionService
from tests.unit.ingestion._fakes import (
    FakeDocumentRepository,
    FakeDocumentVersionRepository,
    FakeExternalObjectRepository,
    FakeSourceRepository,
    FakeStubConnector,
)

# NOTE: No import from lore.connectors.github — ingestion unit tests must be provider-agnostic.


async def test_version_metadata_contains_provenance_snapshot() -> None:
    conn_id = uuid4()
    repo_id = uuid4()
    content = "# Architecture"
    path = "docs/architecture.md"
    payload = {"path": path}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    raw = RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/deadbeef/{path}",
        connection_id=conn_id,
        repository_id=repo_id,
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={
            "commit_sha": "deadbeef",
            "path": path,
            "owner": "owner",
            "repo": "repo",
            "branch": "main",
        },
    )

    ext_obj_repo = FakeExternalObjectRepository()
    source_repo = FakeSourceRepository()
    doc_repo = FakeDocumentRepository()
    dv_repo = FakeDocumentVersionRepository()
    connector = FakeStubConnector()

    svc = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)
    await svc.ingest_sync_result(SyncResult("stub", [raw]), connector)

    assert len(dv_repo.versions) == 1
    version_meta = dv_repo.versions[0].metadata

    assert version_meta["external_id"] == f"owner/repo:file:{path}"
    assert version_meta["external_url"] == f"https://github.com/owner/repo/blob/deadbeef/{path}"
    assert "raw_payload_hash" in version_meta
    assert version_meta["commit_sha"] == "deadbeef"
    assert version_meta["path"] == path
