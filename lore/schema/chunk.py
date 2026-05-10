from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Chunk:
    id: UUID
    document_version_id: UUID
    text: str
    embedding_ref: str | None
    metadata: dict[str, Any]
    created_at: datetime
