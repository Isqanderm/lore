from lore.connector_sdk.errors import UnsupportedCapabilityError


async def verify_webhook(payload: bytes, headers: dict[str, str]) -> bool:
    raise UnsupportedCapabilityError(
        "GitHub webhooks are not supported in this version. "
        "supports_webhooks=False in ConnectorCapabilities."
    )


async def parse_webhook(payload: bytes, headers: dict[str, str]) -> None:
    raise UnsupportedCapabilityError("GitHub webhooks are not supported in this version.")
