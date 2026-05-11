from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lore.connector_sdk.errors import ConnectorConfigurationError

if TYPE_CHECKING:
    from lore.infrastructure.config import Settings


@dataclass(frozen=True)
class GitHubAuth:
    token: str
    auth_mode: str = "env_pat"

    @classmethod
    def from_settings(cls, settings: Settings) -> GitHubAuth:
        if not settings.github_token:
            raise ConnectorConfigurationError(
                "GITHUB_TOKEN is not set. Set the GITHUB_TOKEN environment variable."
            )
        return cls(token=settings.github_token.get_secret_value())
