import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.schema.errors import LoreError, NotFoundError, ValidationError
from lore.sync.errors import RepositoryNotFoundError

logger = structlog.get_logger(__name__)

_STATUS_MAP: dict[type[LoreError], int] = {
    NotFoundError: 404,
    ValidationError: 422,
}

_CODE_MAP: dict[type[LoreError], str] = {
    NotFoundError: "not_found",
    ValidationError: "validation_error",
}


async def lore_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LoreError)
    status_code = _STATUS_MAP.get(type(exc), 400)
    code = _CODE_MAP.get(type(exc), "lore_error")
    logger.warning("lore.error", code=code, message=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": str(exc)}},
    )


async def domain_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    if isinstance(exc, RepositoryNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "repository_not_found", "message": str(exc)}},
        )
    assert isinstance(exc, RepositoryNotSyncedError)
    return JSONResponse(
        status_code=409,
        content={"error": {"code": "repository_not_synced", "message": str(exc)}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("lore.unhandled_error", path=request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Unexpected server error"}},
    )
