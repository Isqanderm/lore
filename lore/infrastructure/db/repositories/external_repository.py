from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select

from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.repositories.base import BaseRepository

if TYPE_CHECKING:
    from datetime import datetime

    from lore.connector_sdk.models import ExternalContainerDraft


@dataclass
class ExternalRepository:
    id: UUID
    connection_id: UUID
    provider: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    html_url: str
    visibility: str | None
    last_synced_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _orm_to_schema(orm: ExternalRepositoryORM) -> ExternalRepository:
    return ExternalRepository(
        id=orm.id,
        connection_id=orm.connection_id,
        provider=orm.provider,
        owner=orm.owner,
        name=orm.name,
        full_name=orm.full_name,
        default_branch=orm.default_branch,
        html_url=orm.html_url,
        visibility=orm.visibility,
        last_synced_at=orm.last_synced_at,
        metadata=orm.metadata_,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class ExternalRepositoryRepository(BaseRepository[ExternalRepositoryORM]):
    async def get_or_create(
        self,
        connection_id: UUID,
        draft: ExternalContainerDraft,
    ) -> ExternalRepository:
        result = await self.session.execute(
            select(ExternalRepositoryORM).where(
                ExternalRepositoryORM.connection_id == connection_id,
                ExternalRepositoryORM.provider == draft.provider,
                ExternalRepositoryORM.full_name == draft.full_name,
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = ExternalRepositoryORM(
                id=uuid4(),
                connection_id=connection_id,
                provider=draft.provider,
                owner=draft.owner,
                name=draft.name,
                full_name=draft.full_name,
                default_branch=draft.default_branch,
                html_url=draft.html_url,
                visibility=draft.visibility,
                last_synced_at=None,
                metadata_=draft.metadata,
            )
            self.session.add(orm)
            await self.session.flush()
        return _orm_to_schema(orm)

    async def mark_synced(self, id: UUID, synced_at: datetime) -> None:
        result = await self.session.execute(
            select(ExternalRepositoryORM).where(ExternalRepositoryORM.id == id)
        )
        orm = result.scalar_one()
        orm.last_synced_at = synced_at
        await self.session.flush()

    async def get_by_id(self, id: UUID) -> ExternalRepository | None:
        result = await self.session.execute(
            select(ExternalRepositoryORM).where(ExternalRepositoryORM.id == id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
