from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.base import BaseRepository


@dataclass
class RepositorySyncRun:
    id: UUID
    repository_id: UUID
    connector_id: str
    trigger: str
    mode: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings: list[str]
    error_message: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _orm_to_schema(orm: RepositorySyncRunORM) -> RepositorySyncRun:
    return RepositorySyncRun(
        id=orm.id,
        repository_id=orm.repository_id,
        connector_id=orm.connector_id,
        trigger=orm.trigger,
        mode=orm.mode,
        status=orm.status,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
        raw_objects_processed=orm.raw_objects_processed,
        documents_created=orm.documents_created,
        versions_created=orm.versions_created,
        versions_skipped=orm.versions_skipped,
        warnings=[str(w) for w in orm.warnings],
        error_message=orm.error_message,
        metadata=dict(orm.metadata_),
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class RepositorySyncRunRepository(BaseRepository[RepositorySyncRunORM]):
    async def create_running(
        self,
        repository_id: UUID,
        connector_id: str,
        trigger: str,
        mode: str,
    ) -> RepositorySyncRun:
        now = datetime.now(UTC)
        orm = RepositorySyncRunORM(
            id=uuid4(),
            repository_id=repository_id,
            connector_id=connector_id,
            trigger=trigger,
            mode=mode,
            status="running",
            started_at=now,
        )
        self.session.add(orm)
        await self.session.flush()
        return _orm_to_schema(orm)

    async def mark_finished(
        self,
        run_id: UUID,
        status: str,
        raw_objects_processed: int,
        documents_created: int,
        versions_created: int,
        versions_skipped: int,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> None:
        result = await self.session.execute(
            select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == run_id)
        )
        orm = result.scalar_one()
        orm.status = status
        orm.finished_at = datetime.now(UTC)
        orm.raw_objects_processed = raw_objects_processed
        orm.documents_created = documents_created
        orm.versions_created = versions_created
        orm.versions_skipped = versions_skipped
        orm.warnings = warnings
        orm.metadata_ = metadata
        await self.session.flush()

    async def mark_failed(self, run_id: UUID, error_message: str) -> None:
        result = await self.session.execute(
            select(RepositorySyncRunORM).where(RepositorySyncRunORM.id == run_id)
        )
        orm = result.scalar_one()
        orm.status = "failed"
        orm.finished_at = datetime.now(UTC)
        orm.error_message = error_message
        # counters remain at 0 — no partial counter recovery
        await self.session.flush()

    async def list_by_repository(
        self,
        repository_id: UUID,
        limit: int = 50,
    ) -> list[RepositorySyncRun]:
        result = await self.session.execute(
            select(RepositorySyncRunORM)
            .where(RepositorySyncRunORM.repository_id == repository_id)
            .order_by(
                RepositorySyncRunORM.started_at.desc(),
                RepositorySyncRunORM.created_at.desc(),
            )
            .limit(limit)
        )
        return [_orm_to_schema(orm) for orm in result.scalars().all()]
