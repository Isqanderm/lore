from dataclasses import dataclass

from lore.connector_sdk.capabilities import ConnectorCapabilities


@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    display_name: str
    version: str
    capabilities: ConnectorCapabilities
