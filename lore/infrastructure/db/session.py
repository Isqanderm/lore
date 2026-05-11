from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from lore.infrastructure.config import get_settings
from lore.infrastructure.db.engine import build_engine

_session_factory: async_sessionmaker[AsyncSession] | None = None


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        settings = get_settings()
        engine = build_engine(settings)
        _session_factory = build_session_factory(engine)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = _get_session_factory()
    async with factory() as session:
        yield session
