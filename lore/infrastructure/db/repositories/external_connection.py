from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from datetime import datetime

from sqlalchemy import select

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.repositories.base import BaseRepository


@dataclass
class ExternalConnection:
    id: UUID
    provider: str
    auth_mode: str
    external_account_id: str | None
    installation_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _orm_to_schema(orm: ExternalConnectionORM) -> ExternalConnection:
    return ExternalConnection(
        id=orm.id,
        provider=orm.provider,
        auth_mode=orm.auth_mode,
        external_account_id=orm.external_account_id,
        installation_id=orm.installation_id,
        metadata=orm.metadata_,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class ExternalConnectionRepository(BaseRepository[ExternalConnectionORM]):
    async def get_or_create_env_pat(self, provider: str) -> ExternalConnection:
        result = await self.session.execute(
            select(ExternalConnectionORM).where(
                ExternalConnectionORM.provider == provider,
                ExternalConnectionORM.auth_mode == "env_pat",
            )
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = ExternalConnectionORM(
                id=uuid4(),
                provider=provider,
                auth_mode="env_pat",
                external_account_id=None,
                installation_id=None,
                metadata_={"token_source": "env", "configured": True},
            )
            self.session.add(orm)
            await self.session.flush()
        return _orm_to_schema(orm)

    async def get_by_id(self, id: UUID) -> ExternalConnection | None:
        result = await self.session.execute(
            select(ExternalConnectionORM).where(ExternalConnectionORM.id == id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_schema(orm) if orm else None
