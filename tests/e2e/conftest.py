from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
import sqlalchemy
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from apps.api.main import create_app
from lore.infrastructure.db.base import Base
from lore.infrastructure.db.models import (  # noqa: F401
    chunk,
    document,
    external_connection,
    external_object,
    external_repository,
    repository_artifact,
    repository_sync_run,
    source,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from fastapi import FastAPI


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    import os

    from lore.infrastructure.config import get_settings

    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    os.environ.setdefault("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


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

    async with engine.begin() as conn:
        await conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))

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


@pytest_asyncio.fixture(loop_scope="session")
async def app_with_db(db_session: AsyncSession, db_url: str) -> AsyncGenerator[FastAPI, None]:
    import os

    from lore.infrastructure.config import get_settings

    os.environ.setdefault("DATABASE_URL", db_url)
    os.environ.setdefault("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()

    from lore.infrastructure.db.session import get_session

    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    yield app
    app.dependency_overrides.clear()
    with contextlib.suppress(AttributeError, KeyError):
        del app.state.connector_registry


@pytest_asyncio.fixture(loop_scope="session")
async def app_client_with_db(app_with_db: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app_with_db)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
