"""Live GitHub integration smoke test. Opt-in only.

Run with:
    GITHUB_TOKEN=ghp_... LIVE_GITHUB_TEST_REPO=owner/repo pytest tests/smoke/ -m live_github -v

Never run in CI.
"""

import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest

from lore.connector_sdk.models import FullSyncRequest
from lore.connectors.github.client import GitHubClient
from lore.connectors.github.connector import GitHubConnector
from lore.connectors.github.file_policy import FileSelectionPolicy
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.config import get_settings


@pytest.fixture
async def live_connector() -> AsyncGenerator[GitHubConnector, None]:
    settings = get_settings()
    client = GitHubClient.from_settings(settings)
    connector = GitHubConnector(
        client=client,
        file_policy=FileSelectionPolicy(),
        normalizer=GitHubNormalizer(),
    )
    yield connector
    await client.close()


@pytest.mark.live_github
async def test_live_inspect_resource(live_connector: GitHubConnector) -> None:
    repo_url = os.environ["LIVE_GITHUB_TEST_REPO"]
    if not repo_url.startswith("https://"):
        repo_url = f"https://github.com/{repo_url}"

    draft = await live_connector.inspect_resource(repo_url)
    assert draft.provider == "github"
    assert draft.full_name != ""
    assert draft.default_branch != ""


@pytest.mark.live_github
async def test_live_full_sync_returns_objects(live_connector: GitHubConnector) -> None:
    repo_url = os.environ["LIVE_GITHUB_TEST_REPO"]
    if not repo_url.startswith("https://"):
        repo_url = f"https://github.com/{repo_url}"

    request = FullSyncRequest(
        connection_id=uuid4(),
        repository_id=uuid4(),
        resource_uri=repo_url,
    )
    result = await live_connector.full_sync(request)
    assert result.connector_id == "github"
    assert len(result.raw_objects) > 0

    types = {r.object_type for r in result.raw_objects}
    assert "github.repository" in types

    all_drafts = []
    for raw in result.raw_objects:
        all_drafts.extend(live_connector.normalize(raw))
    assert len(all_drafts) > 0
