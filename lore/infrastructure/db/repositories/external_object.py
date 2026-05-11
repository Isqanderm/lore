from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert

from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.repositories.base import BaseRepository

if TYPE_CHECKING:
    from datetime import datetime

    from lore.connector_sdk.models import RawExternalObject


@dataclass
class ExternalObject:
    id: UUID
    repository_id: UUID | None
    connection_id: UUID
    provider: str
    object_type: str
    external_id: str
    external_url: str | None
    raw_payload_json: dict[str, Any]
    raw_payload_hash: str
    content: str | None
    content_hash: str | None
    source_updated_at: datetime | None
    fetched_at: datetime
    metadata: dict[str, Any]


class ExternalObjectRepository(BaseRepository[ExternalObjectORM]):
    async def upsert(self, raw: RawExternalObject) -> ExternalObject:
        stmt = (
            insert(ExternalObjectORM)
            .values(
                id=uuid4(),
                repository_id=raw.repository_id,
                connection_id=raw.connection_id,
                provider=raw.provider,
                object_type=raw.object_type,
                external_id=raw.external_id,
                external_url=raw.external_url,
                raw_payload_json=raw.raw_payload,
                raw_payload_hash=raw.raw_payload_hash,
                content=raw.content,
                content_hash=raw.content_hash,
                source_updated_at=raw.source_updated_at,
                fetched_at=raw.fetched_at,
                metadata_=raw.metadata,
            )
            .on_conflict_do_update(
                constraint="uq_external_objects_connection_provider_id",
                set_={
                    "repository_id": raw.repository_id,
                    "object_type": raw.object_type,
                    "external_url": raw.external_url,
                    "raw_payload_json": raw.raw_payload,
                    "raw_payload_hash": raw.raw_payload_hash,
                    "content": raw.content,
                    "content_hash": raw.content_hash,
                    "source_updated_at": raw.source_updated_at,
                    "fetched_at": raw.fetched_at,
                    "metadata": raw.metadata,
                },
            )
            .returning(ExternalObjectORM)
        )
        result = await self.session.execute(stmt)
        orm = result.scalar_one()
        return ExternalObject(
            id=orm.id,
            repository_id=orm.repository_id,
            connection_id=orm.connection_id,
            provider=orm.provider,
            object_type=orm.object_type,
            external_id=orm.external_id,
            external_url=orm.external_url,
            raw_payload_json=orm.raw_payload_json,
            raw_payload_hash=orm.raw_payload_hash,
            content=orm.content,
            content_hash=orm.content_hash,
            source_updated_at=orm.source_updated_at,
            fetched_at=orm.fetched_at,
            metadata=orm.metadata_,
        )
