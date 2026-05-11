from lore.infrastructure.config import Settings
from lore.infrastructure.db.base import Base
from lore.infrastructure.db.engine import build_engine


def test_base_has_metadata() -> None:
    assert Base.metadata is not None


def test_build_engine_returns_engine() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/lore",
        openai_api_key="sk-test",
    )
    engine = build_engine(settings)
    assert engine is not None
