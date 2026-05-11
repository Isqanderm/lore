import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: fast tests without external dependencies")
    config.addinivalue_line("markers", "integration: tests requiring Docker + PostgreSQL")
    config.addinivalue_line("markers", "e2e: end-to-end API tests")
