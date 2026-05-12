from __future__ import annotations


class RepositoryNotSyncedError(Exception):
    def __init__(self, repository_id: object) -> None:
        super().__init__(f"Repository {repository_id} has no succeeded sync run")
        self.repository_id = repository_id
