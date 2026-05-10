import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from apps.api.exception_handlers import lore_exception_handler, unhandled_exception_handler
from lore.schema.errors import LoreError, NotFoundError


@pytest.mark.asyncio
async def test_not_found_error_returns_404() -> None:
    app = FastAPI()
    app.add_exception_handler(LoreError, lore_exception_handler)

    @app.get("/test")
    async def route() -> dict[str, str]:
        raise NotFoundError("thing not found")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "thing not found"}}


@pytest.mark.asyncio
async def test_lore_error_returns_400() -> None:
    app = FastAPI()
    app.add_exception_handler(LoreError, lore_exception_handler)

    @app.get("/test")
    async def route() -> dict[str, str]:
        raise LoreError("bad input")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "lore_error"
