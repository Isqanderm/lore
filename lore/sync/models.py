# lore/sync/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


@dataclass
class RepositorySyncResult:
    sync_run_id: UUID
    repository_id: UUID
    status: str
    trigger: str
    mode: str
    raw_objects_processed: int
    documents_created: int
    versions_created: int
    versions_skipped: int
    warnings: list[str] = field(default_factory=list)
