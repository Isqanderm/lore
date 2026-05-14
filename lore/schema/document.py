from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Document:
    id: UUID
    source_id: UUID
    title: str
    path: str
    created_at: datetime
    updated_at: datetime
    document_kind: str | None = None
    logical_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    deleted_at: datetime | None = None
    first_seen_sync_run_id: UUID | None = None
    last_seen_sync_run_id: UUID | None = None


@dataclass(frozen=True)
class DocumentVersion:
    id: UUID
    document_id: UUID
    version: int
    content: str
    checksum: str
    created_at: datetime
    version_ref: str | None = None
    source_updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
