from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest

GITHUB_CAPABILITIES = ConnectorCapabilities(
    supports_full_sync=True,
    supports_incremental_sync=False,
    supports_webhooks=False,
    supports_repository_tree=True,
    supports_files=True,
    supports_issues=False,
    supports_pull_requests=False,
    supports_comments=False,
    supports_releases=False,
    supports_permissions=False,
    object_types=("github.repository", "github.file"),
)

GITHUB_MANIFEST = ConnectorManifest(
    connector_id="github",
    display_name="GitHub",
    version="0.1.0",
    capabilities=GITHUB_CAPABILITIES,
)
