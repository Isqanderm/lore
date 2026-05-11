import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from lore.connector_sdk.models import RawExternalObject


def _make_raw(
    path: str = "README.md",
    content: str = "# Hello",
    payload: dict[str, Any] | None = None,
) -> RawExternalObject:
    if payload is None:
        payload = {"path": path, "size": len(content)}
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    raw_payload_hash = "sha256:" + hashlib.sha256(canonical_json.encode()).hexdigest()
    content_hash = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    conn_id = uuid4()
    return RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/abc123/{path}",
        connection_id=conn_id,
        repository_id=uuid4(),
        raw_payload=payload,
        raw_payload_hash=raw_payload_hash,
        content=content,
        content_hash=content_hash,
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={"commit_sha": "abc123", "path": path, "owner": "owner", "repo": "repo"},
    )


def test_external_id_stable_by_path() -> None:
    raw = _make_raw(path="lore/service.py")
    assert raw.external_id == "owner/repo:file:lore/service.py"
    assert "abc123" not in raw.external_id


def test_raw_payload_hash_deterministic() -> None:
    payload = {"path": "README.md", "size": 42}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    expected = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    raw = _make_raw(payload=payload)
    assert raw.raw_payload_hash == expected


def test_content_hash_deterministic() -> None:
    raw = _make_raw(content="# Hello World")
    expected = "sha256:" + hashlib.sha256(b"# Hello World").hexdigest()
    assert raw.content_hash == expected


def test_commit_sha_in_metadata() -> None:
    raw = _make_raw()
    assert "commit_sha" in raw.metadata
    assert raw.metadata["commit_sha"] == "abc123"
