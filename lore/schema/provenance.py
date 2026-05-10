from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Provenance:
    """Tracks the origin and transformation history of a knowledge artifact."""

    id: UUID
    entity_id: UUID
    source_id: UUID
    created_at: datetime
