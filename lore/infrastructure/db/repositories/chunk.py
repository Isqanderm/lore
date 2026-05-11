from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

from sqlalchemy import select, text

from lore.infrastructure.db.models.chunk import ChunkORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.chunk import Chunk


def _orm_to_schema(orm: ChunkORM) -> Chunk:
    return Chunk(
        id=orm.id,
        document_version_id=orm.document_version_id,
        text=orm.text,
        embedding_ref=orm.embedding_ref,
        metadata=orm.metadata_json or {},
        created_at=orm.created_at,
    )


class ChunkRepository(BaseRepository[ChunkORM]):
    async def create(self, chunk: Chunk, embedding: list[float] | None = None) -> Chunk:
        orm = ChunkORM(
            id=chunk.id,
            document_version_id=chunk.document_version_id,
            text=chunk.text,
            embedding=embedding,
            embedding_ref=chunk.embedding_ref,
            metadata_json=chunk.metadata,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> Chunk | None:
        result = await self.session.execute(select(ChunkORM).where(ChunkORM.id == id))
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None

    async def update_embedding(
        self, chunk_id: UUID, embedding: list[float], embedding_ref: str
    ) -> None:
        result = await self.session.execute(select(ChunkORM).where(ChunkORM.id == chunk_id))
        orm = result.scalar_one_or_none()
        if orm is not None:
            orm.embedding = embedding
            orm.embedding_ref = embedding_ref
            await self.session.flush()

    async def query_by_vector(self, vec: list[float], limit: int = 10) -> list[Chunk]:
        result = await self.session.execute(
            select(ChunkORM)
            .where(ChunkORM.embedding.is_not(None))
            .order_by(ChunkORM.embedding.l2_distance(vec))
            .limit(limit)
        )
        return [_orm_to_schema(row) for row in result.scalars().all()]

    async def query_by_text(self, query: str, limit: int = 10) -> list[Chunk]:
        result = await self.session.execute(
            select(ChunkORM)
            .where(
                ChunkORM.text_search.op("@@")(
                    text("plainto_tsquery('english', :q)").bindparams(q=query)
                )
            )
            .limit(limit)
        )
        return [_orm_to_schema(row) for row in result.scalars().all()]
