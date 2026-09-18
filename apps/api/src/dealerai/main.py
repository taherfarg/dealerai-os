from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import agents as _agents  # noqa: F401  registers the agents
from . import tools as _tools  # noqa: F401  registers the agent tools
from .config import get_settings
from .core.errors import install_error_handlers
from .core.logging import configure_logging, install_request_context
from .db import session
from .events import handlers as _handlers  # noqa: F401  registers the event handlers
from .routes import (
    approvals,
    channels,
    content,
    dev,
    imports,
    inbox,
    me,
    runs,
    team,
    tenants,
    vehicles,
    webhooks,
)

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
    # The browser calls this API directly (docs/sales/01-architecture.md § 2 A).
    # Bearer tokens, not cookies, so credentials stay off. Added last so it is
    # the outermost middleware and answers preflights before anything else runs.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origin_list,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Tenant-Id", "Idempotency-Key"],
    )
    app.include_router(tenants.router)
    app.include_router(approvals.router)
    app.include_router(vehicles.router)
    app.include_router(imports.router)
    app.include_router(runs.router)
    app.include_router(content.router)
    app.include_router(me.router)
    app.include_router(team.router)
    app.include_router(webhooks.router)
    app.include_router(inbox.router)
    app.include_router(channels.router)
    # Local sign-in as a seeded person. Never mounted outside ENV=local.
    if settings.env == "local":
        app.include_router(dev.router)

    @app.get("/internal/health")
    async def health() -> dict[str, Any]:
        # Degraded connectors must not take the API out of the load balancer;
        # only the database is liveness-critical here.
        return {"status": "ok", "env": settings.env, **await session.healthcheck()}

    return app


app = create_app()
