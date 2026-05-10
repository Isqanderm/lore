from lore.infrastructure.db.repositories.base import BaseRepository
from lore.infrastructure.db.repositories.source import SourceRepository
from lore.infrastructure.db.repositories.document import DocumentRepository, DocumentVersionRepository
from lore.infrastructure.db.repositories.chunk import ChunkRepository


def test_source_repository_inherits_base() -> None:
    assert issubclass(SourceRepository, BaseRepository)


def test_document_repository_inherits_base() -> None:
    assert issubclass(DocumentRepository, BaseRepository)


def test_document_version_repository_inherits_base() -> None:
    assert issubclass(DocumentVersionRepository, BaseRepository)


def test_chunk_repository_inherits_base() -> None:
    assert issubclass(ChunkRepository, BaseRepository)


def test_chunk_repository_has_write_methods() -> None:
    methods = dir(ChunkRepository)
    assert "create" in methods
    assert "update_embedding" in methods


def test_chunk_repository_has_read_methods() -> None:
    methods = dir(ChunkRepository)
    assert "get_by_id" in methods
    assert "query_by_vector" in methods
    assert "query_by_text" in methods
