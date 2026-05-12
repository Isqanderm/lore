from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from uuid import UUID
from sqlalchemy.dialects.postgresql import insert

from lore.infrastructure.db.models.repository_artifact import RepositoryArtifactORM
from lore.infrastructure.db.repositories.base import BaseRepository
from lore.schema.repository_artifact import RepositoryArtifact


def _orm_to_schema(orm: RepositoryArtifactORM) -> RepositoryArtifact:
    return RepositoryArtifact(
        id=orm.id,
        repository_id=orm.repository_id,
        artifact_type=orm.artifact_type,
        title=orm.title,
        content_json=dict(orm.content_json),
        source_sync_run_id=orm.source_sync_run_id,
        generated_at=orm.generated_at,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class RepositoryArtifactRepository(BaseRepository[RepositoryArtifactORM]):
    async def upsert(self, artifact: RepositoryArtifact) -> RepositoryArtifact:
        now = datetime.now(UTC)
        stmt = (
            insert(RepositoryArtifactORM)
            .values(
                id=artifact.id,
                repository_id=artifact.repository_id,
                artifact_type=artifact.artifact_type,
                title=artifact.title,
                content_json=artifact.content_json,
                source_sync_run_id=artifact.source_sync_run_id,
                generated_at=artifact.generated_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_repository_artifact_type",
                set_=dict(
                    title=artifact.title,
                    content_json=artifact.content_json,
                    source_sync_run_id=artifact.source_sync_run_id,
                    generated_at=artifact.generated_at,
                    updated_at=now,
                ),
            )
            .returning(RepositoryArtifactORM)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        orm = result.scalars().one()
        return _orm_to_schema(orm)

    async def get_by_repository_and_type(
        self,
        repository_id: UUID,
        artifact_type: str,
    ) -> RepositoryArtifact | None:
        result = await self.session.execute(
            select(RepositoryArtifactORM).where(
                RepositoryArtifactORM.repository_id == repository_id,
                RepositoryArtifactORM.artifact_type == artifact_type,
            )
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
