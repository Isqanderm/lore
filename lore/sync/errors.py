# lore/sync/errors.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class RepositoryNotFoundError(Exception):
    def __init__(self, repository_id: UUID) -> None:
        super().__init__(f"Repository {repository_id} not found.")


class UnsupportedSyncModeError(Exception):
    def __init__(self, mode: str) -> None:
        super().__init__(
            f"Sync mode '{mode}' is not supported. Only 'full' is supported in this version."
        )
