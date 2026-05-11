from lore.infrastructure.observability.logging import configure_logging


def test_configure_logging_does_not_raise() -> None:
    configure_logging(log_level="DEBUG", environment="development")


def test_configure_logging_production_does_not_raise() -> None:
    configure_logging(log_level="INFO", environment="production")
