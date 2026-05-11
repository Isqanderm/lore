from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/connectors", tags=["connectors"])


class CapabilitiesResponse(BaseModel):
    supports_full_sync: bool
    supports_incremental_sync: bool
    supports_webhooks: bool
    supports_files: bool
    object_types: list[str]


class ConnectorResponse(BaseModel):
    connector_id: str
    display_name: str
    version: str
    capabilities: CapabilitiesResponse


@router.get("", response_model=list[ConnectorResponse])
async def list_connectors(request: Request) -> list[ConnectorResponse]:
    registry = request.app.state.connector_registry
    return [
        ConnectorResponse(
            connector_id=m.connector_id,
            display_name=m.display_name,
            version=m.version,
            capabilities=CapabilitiesResponse(
                supports_full_sync=m.capabilities.supports_full_sync,
                supports_incremental_sync=m.capabilities.supports_incremental_sync,
                supports_webhooks=m.capabilities.supports_webhooks,
                supports_files=m.capabilities.supports_files,
                object_types=list(m.capabilities.object_types),
            ),
        )
        for m in registry.list()
    ]


@router.post("/{connector_id}/webhook", status_code=501)
async def webhook(connector_id: str) -> dict:  # type: ignore[type-arg]
    return {"error": {"code": "not_implemented", "message": "Webhooks not supported yet"}}
