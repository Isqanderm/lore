from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True)
class FullSyncRequest:
    connection_id: UUID
    repository_id: UUID | None
    resource_uri: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IncrementalSyncRequest:
    connection_id: UUID
    repository_id: UUID | None
    resource_uri: str
    cursor: SyncCursor
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SyncCursor:
    value: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEvent:
    event_type: str
    provider: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalContainerDraft:
    provider: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    html_url: str
    visibility: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProvenanceDraft:
    provider: str
    external_id: str
    external_url: str | None
    connection_id: UUID
    repository_id: UUID | None
    raw_payload_hash: str


@dataclass(frozen=True)
class RawExternalObject:
    provider: str
    object_type: str
    external_id: str
    external_url: str | None
    connection_id: UUID
    repository_id: UUID | None
    raw_payload: dict[str, Any]
    raw_payload_hash: str
    content: str | None
    content_hash: str | None
    source_updated_at: datetime | None
    fetched_at: datetime
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CanonicalDocumentDraft:
    document_kind: str
    logical_path: str | None
    title: str
    content: str
    content_hash: str
    version_ref: str | None
    source_updated_at: datetime | None
    provenance: ProvenanceDraft
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SyncResult:
    connector_id: str
    raw_objects: list[RawExternalObject]
    cursor: SyncCursor | None = None
    has_more: bool = False
    warnings: list[str] = field(default_factory=list)
