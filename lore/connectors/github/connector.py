from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.errors import (
    ConnectorAuthenticationError,
    ConnectorError,
    ConnectorRateLimitError,
    UnsupportedCapabilityError,
)
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
    WebhookEvent,
)
from lore.connectors.github.manifest import GITHUB_MANIFEST
from lore.connectors.github.models import GitHubTreeEntry, parse_github_url

if TYPE_CHECKING:
    from lore.connector_sdk.manifest import ConnectorManifest
    from lore.connectors.github.client import GitHubClient
    from lore.connectors.github.file_policy import FileSelectionPolicy
    from lore.connectors.github.normalizer import GitHubNormalizer


def _canonical_hash(payload: dict) -> str:  # type: ignore[type-arg]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


class GitHubConnector(BaseConnector):
    def __init__(
        self,
        client: GitHubClient,
        file_policy: FileSelectionPolicy,
        normalizer: GitHubNormalizer,
    ) -> None:
        self._client = client
        self._file_policy = file_policy
        self._normalizer = normalizer

    @property
    def manifest(self) -> ConnectorManifest:
        return GITHUB_MANIFEST

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        owner, repo = parse_github_url(resource_uri)
        meta = await self._client.get_repository(owner, repo)
        return ExternalContainerDraft(
            provider="github",
            owner=owner,
            name=repo,
            full_name=meta["full_name"],
            default_branch=meta["default_branch"],
            html_url=meta["html_url"],
            visibility=meta.get("visibility"),
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        owner, repo = parse_github_url(request.resource_uri)
        repo_meta = await self._client.get_repository(owner, repo)
        branch: str = repo_meta["default_branch"]

        tree = await self._client.get_repository_tree(owner, repo, branch)
        head_sha = tree.commit_sha  # provenance anchor for all objects in this sync

        repo_raw = self._build_repo_raw(repo_meta, request, head_sha)

        selected = self._file_policy.filter(tree.entries)
        file_raws: list[RawExternalObject] = []
        warnings: list[str] = []
        for entry in selected:
            try:
                content = await self._client.get_file_content(owner, repo, entry.path, head_sha)
            except (ConnectorAuthenticationError, ConnectorRateLimitError):
                raise  # fatal — abort the entire sync
            except ConnectorError as exc:
                warnings.append(f"Skipped {entry.path}: {exc}")
                continue
            # Unexpected exceptions propagate — do not swallow them silently.
            file_raws.append(
                self._build_file_raw(entry, content, request, owner, repo, branch, head_sha)
            )

        return SyncResult(
            connector_id="github",
            raw_objects=[repo_raw, *file_raws],
            warnings=warnings,
        )

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return self._normalizer.normalize(raw)

    async def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        raise UnsupportedCapabilityError("webhooks")

    async def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
        raise UnsupportedCapabilityError("webhooks")

    def _build_repo_raw(
        self,
        repo_meta: dict,  # type: ignore[type-arg]
        request: FullSyncRequest,
        head_sha: str,
    ) -> RawExternalObject:
        owner = repo_meta["owner"]["login"]
        repo = repo_meta["name"]
        payload = {
            "full_name": repo_meta["full_name"],
            "default_branch": repo_meta["default_branch"],
            "description": repo_meta.get("description"),
            "html_url": repo_meta["html_url"],
            "visibility": repo_meta.get("visibility"),
        }
        return RawExternalObject(
            provider="github",
            object_type="github.repository",
            external_id=f"{owner}/{repo}:repository",
            external_url=repo_meta["html_url"],
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash=_canonical_hash(payload),
            content=None,
            content_hash=None,
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={"commit_sha": head_sha, "owner": owner, "repo": repo},
        )

    def _build_file_raw(
        self,
        entry: GitHubTreeEntry,
        content: str,
        request: FullSyncRequest,
        owner: str,
        repo: str,
        branch: str,
        head_sha: str,
    ) -> RawExternalObject:
        payload = {
            "path": entry.path,
            "sha": entry.sha,
            "size": entry.size,
            "mode": entry.mode,
        }
        return RawExternalObject(
            provider="github",
            object_type="github.file",
            external_id=f"{owner}/{repo}:file:{entry.path}",
            external_url=f"https://github.com/{owner}/{repo}/blob/{head_sha}/{entry.path}",
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash=_canonical_hash(payload),
            content=content,
            content_hash=_content_hash(content),
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={
                "commit_sha": head_sha,
                "path": entry.path,
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "size": entry.size,
            },
        )
