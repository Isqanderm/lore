"""Verify mark_seen_in_sync is called for every seen document, even if content is unchanged."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from lore.connector_sdk.models import RawExternalObject, SyncResult
from lore.ingestion.service import IngestionService
from tests.unit.ingestion._fakes import (
    FakeDocumentRepository,
    FakeDocumentVersionRepository,
    FakeExternalObjectRepository,
    FakeSourceRepository,
    FakeStubConnector,
)

pytestmark = pytest.mark.unit


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


async def test_mark_seen_in_sync_called_with_sync_run_id() -> None:
    """mark_seen_in_sync must be called once per document when sync_run_id provided."""
    conn_id, repo_id, sync_run_id = uuid4(), uuid4(), uuid4()
    raw = _raw_file("README.md", "# Hello", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    doc_repo = FakeDocumentRepository()
    svc = IngestionService(
        FakeExternalObjectRepository(),
        FakeSourceRepository(),
        doc_repo,
        FakeDocumentVersionRepository(),
    )

    await svc.ingest_sync_result(sync_result, FakeStubConnector(), sync_run_id=sync_run_id)

    assert len(doc_repo.seen_in_sync_calls) == 1
    _doc_id, called_run_id = doc_repo.seen_in_sync_calls[0]
    assert called_run_id == sync_run_id


async def test_mark_seen_in_sync_called_even_when_content_unchanged() -> None:
    """mark_seen_in_sync must be called even when document version is not created (same hash)."""
    conn_id, repo_id, sync_run_id = uuid4(), uuid4(), uuid4()
    raw = _raw_file("README.md", "# Stable", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    doc_repo = FakeDocumentRepository()
    svc = IngestionService(
        FakeExternalObjectRepository(),
        FakeSourceRepository(),
        doc_repo,
        FakeDocumentVersionRepository(),
    )

    # First call — creates document and version
    await svc.ingest_sync_result(sync_result, FakeStubConnector(), sync_run_id=sync_run_id)
    assert len(doc_repo.seen_in_sync_calls) == 1

    # Second call — same content (no new version), but mark_seen_in_sync still called
    sync_run_id_2 = uuid4()
    await svc.ingest_sync_result(sync_result, FakeStubConnector(), sync_run_id=sync_run_id_2)
    assert len(doc_repo.seen_in_sync_calls) == 2
    assert doc_repo.seen_in_sync_calls[1][1] == sync_run_id_2


async def test_mark_seen_in_sync_not_called_without_sync_run_id() -> None:
    """Legacy import flow (sync_run_id=None) must not call mark_seen_in_sync."""
    conn_id, repo_id = uuid4(), uuid4()
    raw = _raw_file("README.md", "# Hello", conn_id, repo_id)
    sync_result = SyncResult(connector_id="stub", raw_objects=[raw])

    doc_repo = FakeDocumentRepository()
    svc = IngestionService(
        FakeExternalObjectRepository(),
        FakeSourceRepository(),
        doc_repo,
        FakeDocumentVersionRepository(),
    )

    await svc.ingest_sync_result(sync_result, FakeStubConnector())  # no sync_run_id

    assert len(doc_repo.seen_in_sync_calls) == 0
