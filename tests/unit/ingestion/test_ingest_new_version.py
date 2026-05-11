"""Changed content must create a new DocumentVersion."""

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


def _raw_file(path: str, content: str, conn_id, repo_id) -> RawExternalObject:  # type: ignore[no-untyped-def]
    payload = {"path": path}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/abc/{path}",
        connection_id=conn_id,
        repository_id=repo_id,
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={
            "commit_sha": "abc123",
            "path": path,
            "owner": "owner",
            "repo": "repo",
            "branch": "main",
        },
    )


async def test_changed_content_creates_new_version() -> None:
    conn_id = uuid4()
    repo_id = uuid4()

    raw_v1 = _raw_file("README.md", "# v1", conn_id, repo_id)
    raw_v2 = _raw_file("README.md", "# v2", conn_id, repo_id)

    ext_obj_repo = FakeExternalObjectRepository()
    source_repo = FakeSourceRepository()
    doc_repo = FakeDocumentRepository()
    dv_repo = FakeDocumentVersionRepository()
    connector = FakeStubConnector()

    svc = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)

    r1 = await svc.ingest_sync_result(SyncResult("stub", [raw_v1]), connector)
    r2 = await svc.ingest_sync_result(SyncResult("stub", [raw_v2]), connector)

    assert r1.versions_created == 1
    assert r2.versions_created == 1
    assert len(dv_repo.versions) == 2
    versions = sorted(dv_repo.versions, key=lambda v: v.version)
    assert versions[0].version == 1
    assert versions[1].version == 2
