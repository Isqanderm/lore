from __future__ import annotations

from typing import Any

from lore.connector_sdk.models import CanonicalDocumentDraft, ProvenanceDraft, RawExternalObject


def _classify_file(path: str) -> str:
    """Map file path to document_kind."""
    name = path.split("/")[-1]

    if name.startswith("README"):
        return "documentation.readme"

    if path.startswith(".github/workflows/"):
        return "config.ci"

    if name in ("pyproject.toml", "package.json", "setup.cfg", "setup.py"):
        return "config.build"

    if name in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml"):
        return "config.runtime"

    if (
        (path.startswith("tests/") and path.endswith(".py"))
        or name.startswith("test_")
        or name.endswith("_test.py")
    ):
        return "code.test"

    if path.endswith(".md") or path.endswith(".rst"):
        return "documentation.markdown"

    if path.endswith(".py"):
        return "code.file"

    return "code.file"


class GitHubNormalizer:
    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        if raw.object_type == "github.file":
            return [self._normalize_file(raw)]
        # github.repository → future: repository_brief artifact. Skip for now.
        return []

    def _normalize_file(self, raw: RawExternalObject) -> CanonicalDocumentDraft:
        path: str = raw.metadata.get("path", raw.external_id)
        commit_sha: str = raw.metadata["commit_sha"]  # mandatory for file objects
        document_kind = _classify_file(path)
        title = path.split("/")[-1]

        provenance = ProvenanceDraft(
            provider=raw.provider,
            external_id=raw.external_id,
            external_url=raw.external_url,
            connection_id=raw.connection_id,
            repository_id=raw.repository_id,
            raw_payload_hash=raw.raw_payload_hash,
        )

        meta: dict[str, Any] = {
            "commit_sha": commit_sha,
            "path": path,
            "owner": raw.metadata.get("owner"),
            "repo": raw.metadata.get("repo"),
            "branch": raw.metadata.get("branch"),
        }

        return CanonicalDocumentDraft(
            document_kind=document_kind,
            logical_path=path,
            title=title,
            content=raw.content or "",
            content_hash=raw.content_hash or "",
            version_ref=commit_sha,
            source_updated_at=raw.source_updated_at,
            provenance=provenance,
            metadata=meta,
        )
