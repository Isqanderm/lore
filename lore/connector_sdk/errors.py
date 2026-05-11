class ConnectorError(Exception):
    """Base error for all connector failures."""


class ConnectorConfigurationError(ConnectorError):
    """Connector is misconfigured (missing token, invalid setting)."""


class ConnectorAuthenticationError(ConnectorError):
    """Authentication to the external provider failed (401/403)."""


class ConnectorRateLimitError(ConnectorError):
    """External provider rate limit hit (429)."""


class ConnectorNotFoundError(ConnectorError):
    """Requested connector_id is not registered in the registry."""


class ExternalResourceNotFoundError(ConnectorError):
    """Resource URL returned 404 from the external provider."""


class UnsupportedCapabilityError(ConnectorError):
    """Connector does not support this capability."""
