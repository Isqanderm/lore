from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    openai_api_key: SecretStr
    log_level: str = "INFO"
    environment: Literal["development", "production"] = "development"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int | None = None
    github_token: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
