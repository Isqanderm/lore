from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from lore.infrastructure.db.base import Base
from lore.infrastructure.db.models import chunk, document, source  # noqa: F401


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
def postgres_container() -> PostgresContainer:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()  # type: ignore[no-any-return]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_url, echo=False)

    # Enable pgvector extension
    async with engine.begin() as conn:
        await conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # Create all tables via ORM metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
