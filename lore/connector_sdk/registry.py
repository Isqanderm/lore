from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.errors import ConnectorNotFoundError
from lore.connector_sdk.manifest import ConnectorManifest


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        self._connectors[connector.connector_id] = connector

    def get(self, connector_id: str) -> BaseConnector:
        if connector_id not in self._connectors:
            raise ConnectorNotFoundError(f"Connector '{connector_id}' is not registered")
        return self._connectors[connector_id]

    def list(self) -> list[ConnectorManifest]:
        return [c.manifest for c in self._connectors.values()]

    def has(self, connector_id: str) -> bool:
        return connector_id in self._connectors
