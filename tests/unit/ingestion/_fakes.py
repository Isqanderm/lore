from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import CanonicalDocumentDraft, ProvenanceDraft, RawExternalObject
from lore.schema.source import Source

if TYPE_CHECKING:
    from datetime import datetime

    from lore.schema.document import Document, DocumentVersion

# NOTE: This file must NOT import from lore.connectors.github.
# FakeStubConnector produces CanonicalDocumentDraft directly — no provider-specific logic.


@dataclass
class FakeExternalObject:
    id: UUID
    connection_id: UUID
    provider: str
    object_type: str
    external_id: str
    external_url: str | None
    raw_payload_hash: str
    content: str | None
    content_hash: str | None
    repository_id: UUID | None
    source_updated_at: None
    fetched_at: datetime
    raw_payload_json: dict  # type: ignore[type-arg]
    metadata: dict  # type: ignore[type-arg]


class FakeExternalObjectRepository:
    def __init__(self) -> None:
        self._by_key: dict[tuple[UUID, str, str], FakeExternalObject] = {}

    async def upsert(self, raw: RawExternalObject) -> FakeExternalObject:
        key = (raw.connection_id, raw.provider, raw.external_id)
        obj = FakeExternalObject(
            id=uuid4(),
            connection_id=raw.connection_id,
            provider=raw.provider,
            object_type=raw.object_type,
            external_id=raw.external_id,
            external_url=raw.external_url,
            raw_payload_hash=raw.raw_payload_hash,
            content=raw.content,
            content_hash=raw.content_hash,
            repository_id=raw.repository_id,
            source_updated_at=None,
            fetched_at=raw.fetched_at,
            raw_payload_json=raw.raw_payload,
            metadata=raw.metadata,
        )
        if key in self._by_key:
            obj = FakeExternalObject(**{**obj.__dict__, "id": self._by_key[key].id})
        self._by_key[key] = obj
        return obj


class FakeSourceRepository:
    def __init__(self) -> None:
        self.sources: list[Source] = []

    async def get_by_external_object_id(self, external_object_id: UUID) -> Source | None:
        return next((s for s in self.sources if s.external_object_id == external_object_id), None)

    async def create_with_external_object(self, source: Source, external_object_id: UUID) -> Source:
        s = Source(
            id=source.id,
            source_type_raw=source.source_type_raw,
            source_type_canonical=source.source_type_canonical,
            origin=source.origin,
            created_at=source.created_at,
            updated_at=source.updated_at,
            external_object_id=external_object_id,
        )
        self.sources.append(s)
        return s


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.documents: list[Document] = []
        self.seen_in_sync_calls: list[tuple[UUID, UUID]] = []  # (document_id, sync_run_id)

    async def get_by_source_kind_path(
        self, source_id: UUID, document_kind: str, logical_path: str | None
    ) -> Document | None:
        return next(
            (
                d
                for d in self.documents
                if d.source_id == source_id
                and d.document_kind == document_kind
                and d.logical_path == logical_path
            ),
            None,
        )

    async def create(self, doc: Document) -> Document:
        self.documents.append(doc)
        return doc

    async def mark_seen_in_sync(self, document_id: UUID, sync_run_id: UUID) -> None:
        self.seen_in_sync_calls.append((document_id, sync_run_id))


class FakeDocumentVersionRepository:
    def __init__(self) -> None:
        self.versions: list[DocumentVersion] = []

    async def get_latest_version(self, document_id: UUID) -> DocumentVersion | None:
        doc_versions = [v for v in self.versions if v.document_id == document_id]
        if not doc_versions:
            return None
        return max(doc_versions, key=lambda v: v.version)

    async def get_max_version(self, document_id: UUID) -> int:
        doc_versions = [v for v in self.versions if v.document_id == document_id]
        return max((v.version for v in doc_versions), default=0)

    async def create(self, dv: DocumentVersion) -> DocumentVersion:
        self.versions.append(dv)
        return dv


class FakeStubConnector(BaseConnector):
    """Stub connector — returns deterministic CanonicalDocumentDraft.

    Does NOT import or use any concrete connector (GitHubNormalizer etc.).
    Unit tests for IngestionService should use this fake exclusively.
    """

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id="stub",
            display_name="Stub",
            version="0.0.1",
            capabilities=ConnectorCapabilities(
                supports_full_sync=False,
                supports_incremental_sync=False,
                supports_webhooks=False,
                supports_repository_tree=False,
                supports_files=False,
                supports_issues=False,
                supports_pull_requests=False,
                supports_comments=False,
                supports_releases=False,
                supports_permissions=False,
                object_types=(),
            ),
        )

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        if raw.content is None:
            return []
        path = raw.metadata.get("path", "doc")
        provenance = ProvenanceDraft(
            provider=raw.provider,
            external_id=raw.external_id,
            external_url=raw.external_url,
            connection_id=raw.connection_id,
            repository_id=raw.repository_id,
            raw_payload_hash=raw.raw_payload_hash,
        )
        return [
            CanonicalDocumentDraft(
                document_kind="documentation.readme",
                logical_path=path if path else None,
                title=path.split("/")[-1] if path else "doc",
                content=raw.content,
                content_hash=raw.content_hash or "",
                version_ref=raw.metadata.get("commit_sha"),
                source_updated_at=raw.source_updated_at,
                provenance=provenance,
                metadata={
                    "commit_sha": raw.metadata.get("commit_sha"),
                    "path": path,
                    "external_id": raw.external_id,
                    "external_url": raw.external_url,
                    "raw_payload_hash": raw.raw_payload_hash,
                },
            )
        ]
