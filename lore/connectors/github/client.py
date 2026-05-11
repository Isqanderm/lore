from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import httpx

from lore.connector_sdk.errors import (
    ConnectorAuthenticationError,
    ConnectorError,
    ConnectorRateLimitError,
    ExternalResourceNotFoundError,
)
from lore.connectors.github.models import GitHubRepositoryTree, GitHubTreeEntry

if TYPE_CHECKING:
    from lore.connectors.github.auth import GitHubAuth
    from lore.infrastructure.config import Settings


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self, auth: GitHubAuth) -> None:
        self._auth = auth
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {auth.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> GitHubClient:
        from lore.connectors.github.auth import GitHubAuth

        return cls(GitHubAuth.from_settings(settings))

    async def close(self) -> None:
        await self._client.aclose()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401 or response.status_code == 403:
            raise ConnectorAuthenticationError(
                f"GitHub authentication failed: HTTP {response.status_code}"
            )
        if response.status_code == 404:
            raise ExternalResourceNotFoundError(f"GitHub resource not found: {response.url}")
        if response.status_code == 429:
            raise ConnectorRateLimitError("GitHub API rate limit exceeded")
        if response.status_code >= 500:
            raise ConnectorError(f"GitHub API server error: HTTP {response.status_code}")
        response.raise_for_status()

    async def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        response = await self._client.get(f"/repos/{owner}/{repo}")
        self._raise_for_status(response)
        return response.json()  # type: ignore[no-any-return]

    async def get_repository_tree(self, owner: str, repo: str, branch: str) -> GitHubRepositoryTree:
        """Atomically resolve branch → commit SHA → tree entries."""
        # 1. Resolve branch → commit SHA
        ref_response = await self._client.get(f"/repos/{owner}/{repo}/git/refs/heads/{branch}")
        self._raise_for_status(ref_response)
        ref_data = ref_response.json()
        commit_sha: str = ref_data["object"]["sha"]

        # 2. Resolve commit SHA → tree SHA
        commit_response = await self._client.get(f"/repos/{owner}/{repo}/git/commits/{commit_sha}")
        self._raise_for_status(commit_response)
        commit_data = commit_response.json()
        tree_sha: str = commit_data["tree"]["sha"]

        # 3. Fetch recursive tree
        tree_response = await self._client.get(
            f"/repos/{owner}/{repo}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        )
        self._raise_for_status(tree_response)
        tree_data = tree_response.json()

        entries = [
            GitHubTreeEntry(
                path=item["path"],
                mode=item["mode"],
                type=item["type"],
                sha=item["sha"],
                size=item.get("size"),
            )
            for item in tree_data.get("tree", [])
        ]

        return GitHubRepositoryTree(
            branch=branch,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            entries=entries,
        )

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        """Fetch file content decoded from base64. Raises ConnectorError for binary files."""
        response = await self._client.get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        self._raise_for_status(response)
        data = response.json()
        encoded = data.get("content", "")
        raw_bytes = base64.b64decode(encoded.replace("\n", ""))
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConnectorError(
                f"File {path} in {owner}/{repo} is not valid UTF-8 (binary?)"
            ) from exc
