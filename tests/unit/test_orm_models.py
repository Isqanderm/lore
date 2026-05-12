from lore.infrastructure.db.models.chunk import ChunkORM
from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.source import SourceORM


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


def test_repository_artifact_orm_table_name() -> None:
    from lore.infrastructure.db.models.repository_artifact import RepositoryArtifactORM

    assert RepositoryArtifactORM.__tablename__ == "repository_artifacts"


def test_repository_artifact_orm_has_required_columns() -> None:
    from lore.infrastructure.db.models.repository_artifact import RepositoryArtifactORM

    cols = {c.name for c in RepositoryArtifactORM.__table__.columns}
    assert "id" in cols
    assert "repository_id" in cols
    assert "artifact_type" in cols
    assert "content_json" in cols
    assert "source_sync_run_id" in cols
    assert "generated_at" in cols
