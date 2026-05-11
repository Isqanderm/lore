from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog

from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.client import GitHubClient
from lore.connectors.github.connector import GitHubConnector
from lore.connectors.github.file_policy import FileSelectionPolicy
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    registry = ConnectorRegistry()
    github_client: GitHubClient | None = None

    if settings.github_token:
        github_client = GitHubClient.from_settings(settings)
        registry.register(
            GitHubConnector(
                client=github_client,
                file_policy=FileSelectionPolicy(),
                normalizer=GitHubNormalizer(),
            )
        )
        logger.info("connector.registered", connector_id="github")
    else:
        logger.warning("connector.github.skipped", reason="GITHUB_TOKEN not set")

    app.state.connector_registry = registry

    logger.info("lore.startup")
    try:
        yield
    finally:
        if github_client is not None:
            await github_client.close()
        logger.info("lore.shutdown")
