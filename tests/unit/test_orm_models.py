from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.chunk import ChunkORM


def test_source_orm_table_name() -> None:
    assert SourceORM.__tablename__ == "sources"


def test_document_orm_table_name() -> None:
    assert DocumentORM.__tablename__ == "documents"


def test_document_version_orm_table_name() -> None:
    assert DocumentVersionORM.__tablename__ == "document_versions"


def test_chunk_orm_table_name() -> None:
    assert ChunkORM.__tablename__ == "chunks"


def test_chunk_has_required_columns() -> None:
    cols = {c.name for c in ChunkORM.__table__.columns}
    assert "embedding" in cols
    assert "embedding_ref" in cols
    assert "text_search" in cols
    assert "metadata_json" in cols
