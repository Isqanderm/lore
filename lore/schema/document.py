from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Document:
    id: UUID
    source_id: UUID
    title: str
    path: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentVersion:
    id: UUID
    document_id: UUID
    version: int
    content: str
    checksum: str
    created_at: datetime
