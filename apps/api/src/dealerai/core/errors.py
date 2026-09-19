"""RFC 9457 problem+json. Every error the API emits has this shape."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()

ERROR_BASE = "https://api.dealerai.os/errors"


class AppError(Exception):
    status: int = 500
    slug: str = "internal"
    title: str = "Internal server error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = errors or []


class NotFound(AppError):
    """Also raised for cross-tenant access. Never 403 — that confirms the row exists."""

    status = 404
    slug = "not-found"
    title = "Not found"


class Forbidden(AppError):
    status = 403
    slug = "forbidden"
    title = "Insufficient role for this action"


class Conflict(AppError):
    status = 409
    slug = "conflict"
    title = "Conflict"


class Unusable(AppError):
    """The request was well-formed and its content was not — a CSV with no
    header row, a mapping naming a column that does not exist."""

    status = 422
    slug = "unusable-input"
    title = "The submitted content cannot be used"


class GuardRejected(AppError):
    status = 422
    slug = "guard-rejected"
    title = "Rejected by a guard"


class WindowClosed(AppError):
    """WhatsApp's 24-hour service window, refused before the connector is called.

    Its own type because the composer answers it by offering templates rather
    than by showing an error (docs/sales/06-api-contract.md § 11).
    """

    status = 422
    slug = "window-closed"
    title = "The 24-hour window is closed"


class ConsentRequired(AppError):
    status = 422
    slug = "consent-required"
    title = "The customer has not agreed to this message"


class ChannelUnavailable(AppError):
    status = 409
    slug = "channel-unavailable"
    title = "The channel cannot send right now"


class BudgetExceeded(AppError):
    status = 422
    slug = "budget-exceeded"
    title = "Tenant AI budget exhausted"


class UpstreamUnavailable(AppError):
    status = 503
    slug = "upstream-unavailable"
    title = "Platform temporarily unavailable"


def _problem(
    *,
    status: int,
    slug: str,
    title: str,
    detail: str | None,
    instance: str,
    trace_id: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{ERROR_BASE}/{slug}",
        "title": title,
        "status": status,
        "instance": instance,
        "trace_id": trace_id,
    }
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "-")
        log.warning("app_error", slug=exc.slug, detail=exc.detail, trace_id=trace_id)
        return _problem(
            status=exc.status,
            slug=exc.slug,
            title=exc.title,
            detail=exc.detail,
            instance=request.url.path,
            trace_id=trace_id,
            errors=exc.errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Routing 404s and dependency-raised HTTPExceptions would otherwise
        # return Starlette's {"detail": ...} shape, so a client would need two
        # error parsers. One shape, always.
        slug = {401: "unauthorized", 403: "forbidden", 404: "not-found", 429: "rate-limited"}.get(
            exc.status_code, "error"
        )
        return _problem(
            status=exc.status_code,
            slug=slug,
            title=str(exc.detail),
            detail=None,
            instance=request.url.path,
            trace_id=getattr(request.state, "trace_id", "-"),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            status=400,
            slug="invalid-request",
            title="Invalid request",
            detail="One or more fields failed validation.",
            instance=request.url.path,
            trace_id=getattr(request.state, "trace_id", "-"),
            errors=[
                {"field": ".".join(str(p) for p in e["loc"][1:]), "code": e["type"]}
                for e in exc.errors()
            ],
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "-")
        log.exception("unhandled", trace_id=trace_id)
        # Deliberately no detail: an unhandled exception's message may contain
        # a query, a token, or another tenant's data.
        return _problem(
            status=500,
            slug="internal",
            title="Internal server error",
            detail=None,
            instance=request.url.path,
            trace_id=trace_id,
        )
