from uuid import UUID

from sqlalchemy import select

from lore.infrastructure.db.models.source import SourceORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.source import Source, SourceType


def _orm_to_schema(orm: SourceORM) -> Source:
    return Source(
        id=orm.id,
        source_type_raw=orm.source_type_raw,
        source_type_canonical=SourceType(orm.source_type_canonical),
        origin=orm.origin,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        external_object_id=orm.external_object_id,
    )


class SourceRepository(BaseRepository[SourceORM]):
    async def create(self, source: Source) -> Source:
        orm = SourceORM(
            id=source.id,
            source_type_raw=source.source_type_raw,
            source_type_canonical=source.source_type_canonical.value,
            origin=source.origin,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> Source | None:
        result = await self.session.execute(select(SourceORM).where(SourceORM.id == id))
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None

    async def get_by_external_object_id(self, external_object_id: UUID) -> Source | None:
        result = await self.session.execute(
            select(SourceORM).where(SourceORM.external_object_id == external_object_id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None

    async def create_with_external_object(
        self,
        source: Source,
        external_object_id: UUID,
    ) -> Source:
        orm = SourceORM(
            id=source.id,
            source_type_raw=source.source_type_raw,
            source_type_canonical=source.source_type_canonical.value,
            origin=source.origin,
            external_object_id=external_object_id,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)
