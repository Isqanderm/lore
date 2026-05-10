import pytest
from uuid import uuid4
from datetime import datetime, timezone
from lore.schema.document import Document, DocumentVersion


def test_document_frozen() -> None:
    doc = Document(
        id=uuid4(),
        source_id=uuid4(),
        title="Architecture Decision Record",
        path="docs/adr/001-database.md",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        doc.title = "mutated"  # type: ignore[misc]


def test_document_version_checksum() -> None:
    dv = DocumentVersion(
        id=uuid4(),
        document_id=uuid4(),
        version=1,
        content="# Hello",
        checksum="sha256:abc123",
        created_at=datetime.now(timezone.utc),
    )
    assert dv.version == 1
    assert dv.checksum.startswith("sha256:")
