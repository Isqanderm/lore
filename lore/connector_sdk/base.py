from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from lore.connector_sdk.errors import UnsupportedCapabilityError

if TYPE_CHECKING:
    from lore.connector_sdk.manifest import ConnectorManifest
    from lore.connector_sdk.models import (
        CanonicalDocumentDraft,
        ExternalContainerDraft,
        FullSyncRequest,
        IncrementalSyncRequest,
        RawExternalObject,
        SyncResult,
        WebhookEvent,
    )


class BaseConnector(ABC):
    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest: ...

    @property
    def connector_id(self) -> str:
        return self.manifest.connector_id

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        raise UnsupportedCapabilityError("inspect_resource")

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raise UnsupportedCapabilityError("full_sync")

    async def incremental_sync(self, request: IncrementalSyncRequest) -> SyncResult:
        raise UnsupportedCapabilityError("incremental_sync")

    async def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        raise UnsupportedCapabilityError("webhooks")

    async def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
        raise UnsupportedCapabilityError("webhooks")

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        raise UnsupportedCapabilityError("normalization")
