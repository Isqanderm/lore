from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import create_app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
