from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI

from .config import get_settings
from .core.errors import install_error_handlers
from .core.logging import configure_logging, install_request_context
from .db import session
from .routes import tenants

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await session.init_pool()
    log.info("api_started", env=settings.env)
    try:
        yield
    finally:
        await session.close_pool()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="DealerAI OS",
        version="0.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_local else None,
    )
    install_request_context(app)
    install_error_handlers(app)
    app.include_router(tenants.router)

    @app.get("/internal/health")
    async def health() -> dict[str, Any]:
        # Degraded connectors must not take the API out of the load balancer;
        # only the database is liveness-critical here.
        return {"status": "ok", "env": settings.env, **await session.healthcheck()}

    return app


app = create_app()
