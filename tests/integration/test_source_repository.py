from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lore.infrastructure.db.repositories.source import SourceRepository
from lore.schema.source import Source, SourceType


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_and_get_source(db_session: AsyncSession) -> None:
    repo = SourceRepository(db_session)
    source = Source(
        id=uuid4(),
        source_type_raw="github",
        source_type_canonical=SourceType.GIT_REPO,
        origin="https://github.com/example/lore",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    created = await repo.create(source)
    assert created.id == source.id
    assert created.source_type_canonical == SourceType.GIT_REPO

    fetched = await repo.get_by_id(source.id)
    assert fetched is not None
    assert fetched.origin == "https://github.com/example/lore"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_nonexistent_source_returns_none(db_session: AsyncSession) -> None:
    repo = SourceRepository(db_session)
    result = await repo.get_by_id(uuid4())
    assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_source_type_canonical_preserved(db_session: AsyncSession) -> None:
    repo = SourceRepository(db_session)
    source = Source(
        id=uuid4(),
        source_type_raw="gitlab",
        source_type_canonical=SourceType.GIT_REPO,
        origin="https://gitlab.com/example/lore",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    created = await repo.create(source)
    assert created.source_type_raw == "gitlab"
    assert created.source_type_canonical == SourceType.GIT_REPO
