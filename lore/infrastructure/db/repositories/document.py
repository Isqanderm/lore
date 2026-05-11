from uuid import UUID

from sqlalchemy import select

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.document import Document, DocumentVersion


def _doc_orm_to_schema(orm: DocumentORM) -> Document:
    return Document(
        id=orm.id,
        source_id=orm.source_id,
        title=orm.title,
        path=orm.path,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _dv_orm_to_schema(orm: DocumentVersionORM) -> DocumentVersion:
    return DocumentVersion(
        id=orm.id,
        document_id=orm.document_id,
        version=orm.version,
        content=orm.content,
        checksum=orm.checksum,
        created_at=orm.created_at,
    )


class DocumentRepository(BaseRepository[DocumentORM]):
    async def create(self, doc: Document) -> Document:
        orm = DocumentORM(
            id=doc.id,
            source_id=doc.source_id,
            title=doc.title,
            path=doc.path,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _doc_orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> Document | None:
        result = await self.session.execute(select(DocumentORM).where(DocumentORM.id == id))
        orm = result.scalar_one_or_none()
        return _doc_orm_to_schema(orm) if orm else None


class DocumentVersionRepository(BaseRepository[DocumentVersionORM]):
    async def create(self, dv: DocumentVersion) -> DocumentVersion:
        orm = DocumentVersionORM(
            id=dv.id,
            document_id=dv.document_id,
            version=dv.version,
            content=dv.content,
            checksum=dv.checksum,
            created_at=dv.created_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _dv_orm_to_schema(orm)
