from fastapi import FastAPI

from apps.api.exception_handlers import lore_exception_handler, unhandled_exception_handler
from apps.api.lifespan import lifespan
from apps.api.routes.v1.health import router as health_router
from lore.infrastructure.config import get_settings
from lore.infrastructure.observability.logging import configure_logging
from lore.infrastructure.observability.middleware import RequestIDMiddleware
from lore.schema.errors import LoreError


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, environment=settings.environment)

    app = FastAPI(title="Lore", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)

    v1_router = FastAPI()
    v1_router.include_router(health_router)
    app.mount("/api/v1", v1_router)

    app.add_exception_handler(LoreError, lore_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


app = create_app()
