from fastapi import APIRouter, FastAPI

from apps.api.exception_handlers import (
    domain_error_handler,
    lore_exception_handler,
    unhandled_exception_handler,
)
from apps.api.lifespan import lifespan
from apps.api.routes.v1.connectors import router as connectors_router
from apps.api.routes.v1.health import router as health_router
from apps.api.routes.v1.repositories import router as repositories_router
from apps.api.routes.v1.repository_artifacts import router as repository_artifacts_router
from lore.artifacts.errors import RepositoryNotSyncedError
from lore.infrastructure.config import get_settings
from lore.infrastructure.observability.logging import configure_logging
from lore.infrastructure.observability.middleware import RequestIDMiddleware
from lore.schema.errors import LoreError
from lore.sync.errors import RepositoryNotFoundError


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, environment=settings.environment)

    app = FastAPI(title="Lore", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(health_router)
    api_v1.include_router(connectors_router)
    api_v1.include_router(repositories_router)
    api_v1.include_router(repository_artifacts_router)
    app.include_router(api_v1)

    app.add_exception_handler(RepositoryNotFoundError, domain_error_handler)
    app.add_exception_handler(RepositoryNotSyncedError, domain_error_handler)
    app.add_exception_handler(LoreError, lore_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app
