from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectorCapabilities:
    supports_full_sync: bool
    supports_incremental_sync: bool
    supports_webhooks: bool
    supports_repository_tree: bool
    supports_files: bool
    supports_issues: bool
    supports_pull_requests: bool
    supports_comments: bool
    supports_releases: bool
    supports_permissions: bool
    object_types: tuple[str, ...]
