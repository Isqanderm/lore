import pytest
from lore.infrastructure.config import Settings


def test_settings_has_required_fields() -> None:
    s = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/lore",
        openai_api_key="sk-test",
    )
    assert s.environment == "development"
    assert s.log_level == "INFO"
    assert s.embedding_model == "text-embedding-3-large"
    assert s.embedding_dimensions is None


def test_settings_rejects_invalid_environment() -> None:
    with pytest.raises(Exception):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/lore",
            openai_api_key="sk-test",
            environment="staging",  # type: ignore[arg-type]
        )
