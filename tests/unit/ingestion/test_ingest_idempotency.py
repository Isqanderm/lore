"""Same content_hash on re-sync must NOT create a duplicate DocumentVersion."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from lore.connector_sdk.models import (
    RawExternalObject,
    SyncResult,
)
from lore.ingestion.service import IngestionService
from tests.unit.ingestion._fakes import (
    FakeDocumentRepository,
    FakeDocumentVersionRepository,
    FakeExternalObjectRepository,
    FakeSourceRepository,
    FakeStubConnector,
)

# NOTE: No import from lore.connectors.github — ingestion unit tests must be provider-agnostic.


def _raw_file(path: str, content: str, conn_id: UUID, repo_id: UUID) -> RawExternalObject:
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


async def test_same_content_no_duplicate_version() -> None:
    conn_id = uuid4()
    repo_id = uuid4()
    raw = _raw_file("README.md", "# Hello", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    ext_obj_repo = FakeExternalObjectRepository()
    source_repo = FakeSourceRepository()
    doc_repo = FakeDocumentRepository()
    dv_repo = FakeDocumentVersionRepository()
    connector = FakeStubConnector()

    svc = IngestionService(ext_obj_repo, source_repo, doc_repo, dv_repo)

    report1 = await svc.ingest_sync_result(sync_result, connector)
    report2 = await svc.ingest_sync_result(sync_result, connector)

    assert report1.documents_created == 1
    assert report1.versions_created == 1
    assert report2.documents_created == 0  # document already exists
    assert report2.versions_created == 0  # same checksum — skipped
    assert len(dv_repo.versions) == 1  # only one version in DB
