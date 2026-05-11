from datetime import UTC, datetime
from uuid import uuid4

from lore.schema.chunk import Chunk


def test_chunk_without_embedding_ref() -> None:
    chunk = Chunk(
        id=uuid4(),
        document_version_id=uuid4(),
        text="The system uses PostgreSQL as primary store.",
        embedding_ref=None,
        metadata={},
        created_at=datetime.now(UTC),
    )
    assert chunk.embedding_ref is None


def test_chunk_with_embedding_ref() -> None:
    chunk = Chunk(
        id=uuid4(),
        document_version_id=uuid4(),
        text="example",
        embedding_ref="openai:text-embedding-3-large:v1:abc123",
        metadata={"source": "adr"},
        created_at=datetime.now(UTC),
    )
    assert chunk.embedding_ref is not None
    parts = chunk.embedding_ref.split(":")
    assert len(parts) == 4
    assert parts[0] == "openai"
