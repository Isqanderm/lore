from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from uuid import UUID

from lore.infrastructure.db.models.document import DocumentORM, DocumentVersionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.source import SourceORM
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
        document_kind=orm.document_kind,
        logical_path=orm.logical_path,
        metadata=orm.metadata_,
    )


def _dv_orm_to_schema(orm: DocumentVersionORM) -> DocumentVersion:
    return DocumentVersion(
        id=orm.id,
        document_id=orm.document_id,
        version=orm.version,
        content=orm.content,
        checksum=orm.checksum,
        created_at=orm.created_at,
        version_ref=orm.version_ref,
        source_updated_at=orm.source_updated_at,
        metadata=orm.metadata_,
    )


class DocumentRepository(BaseRepository[DocumentORM]):
    async def create(self, doc: Document) -> Document:
        orm = DocumentORM(
            id=doc.id,
            source_id=doc.source_id,
            title=doc.title,
            path=doc.path,
            document_kind=doc.document_kind,
            logical_path=doc.logical_path,
            metadata_=doc.metadata,
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

    async def get_document_paths_by_repository_id(self, repository_id: UUID) -> list[str]:
        result = await self.session.execute(
            select(DocumentORM.path)
            .distinct()
            .join(SourceORM, DocumentORM.source_id == SourceORM.id)
            .join(ExternalObjectORM, SourceORM.external_object_id == ExternalObjectORM.id)
            .where(
                ExternalObjectORM.repository_id == repository_id,
                ExternalObjectORM.object_type == "github.file",
            )
            .order_by(DocumentORM.path)
        )
        return list(result.scalars().all())

    async def get_by_source_kind_path(
        self,
        source_id: UUID,
        document_kind: str,
        logical_path: str | None,
    ) -> Document | None:
        if logical_path is None:
            result = await self.session.execute(
                select(DocumentORM).where(
                    DocumentORM.source_id == source_id,
                    DocumentORM.document_kind == document_kind,
                    DocumentORM.logical_path.is_(None),
                )
            )
        else:
            result = await self.session.execute(
                select(DocumentORM).where(
                    DocumentORM.source_id == source_id,
                    DocumentORM.document_kind == document_kind,
                    DocumentORM.logical_path == logical_path,
                )
            )
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
            version_ref=dv.version_ref,
            source_updated_at=dv.source_updated_at,
            metadata_=dv.metadata,
            created_at=dv.created_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _dv_orm_to_schema(orm)

    async def get_latest_version(self, document_id: UUID) -> DocumentVersion | None:
        from sqlalchemy import desc

        result = await self.session.execute(
            select(DocumentVersionORM)
            .where(DocumentVersionORM.document_id == document_id)
            .order_by(desc(DocumentVersionORM.version))
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        return _dv_orm_to_schema(orm) if orm else None

    async def get_max_version(self, document_id: UUID) -> int:
        from sqlalchemy import func as sqlfunc

        result = await self.session.execute(
            select(sqlfunc.max(DocumentVersionORM.version)).where(
                DocumentVersionORM.document_id == document_id
            )
        )
        return result.scalar_one_or_none() or 0
