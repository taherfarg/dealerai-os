"""The only module in the codebase that acquires a database connection.

Enforced by tests/test_import_contracts.py. That constraint is what makes the
`SET LOCAL app.tenant_id` guarantee actually hold: if any other module could
open its own connection, it could open one with no tenant context and RLS would
have nothing to filter on.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import asyncpg

from ..config import get_settings

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    # asyncpg hands back jsonb as str by default; every jsonb column in this
    # schema is a dict or a list at the application layer.
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init_pool(dsn: str | None = None) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn or settings.database_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            init=_init_connection,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _require_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("connection pool not initialised; call init_pool() first")
    return _pool


#: What a caller may see: their own rows, their teams' rows, or everything.
SCOPES = ("own", "team", "all")


@contextlib.asynccontextmanager
async def tenant_session(
    tenant_id: UUID | str,
    *,
    user_id: UUID | str | None = None,
    scope: str = "all",
) -> AsyncIterator[asyncpg.Connection]:
    """Open a transaction scoped to one tenant, and optionally to one person.

    `scope` is what that person may see — own, team or all — and the visibility
    policies in 0006_sales_core.sql filter on it. The worker keeps the default:
    it acts on rows that were already routed.

    All three settings use SET LOCAL (set_config(..., true)), which is
    transaction-scoped, so a pooled connection cannot carry a tenant *or a user*
    into the next request. Plain SET would, which is why it is never used here.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; expected one of {SCOPES}")
    async with _require_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """select set_config('app.tenant_id', $1, true),
                          set_config('app.user_id', $2, true),
                          set_config('app.scope', $3, true)""",
                str(tenant_id),
                str(user_id) if user_id else "",
                scope,
            )
            yield conn


@contextlib.asynccontextmanager
async def system_session() -> AsyncIterator[asyncpg.Connection]:
    """A connection with NO tenant context.

    Legitimate uses are the event-queue claim, webhook delivery routing (both
    run before the tenant is known), and the health check. Everything else must
    go through tenant_session. Under RLS this session can see nothing
    tenant-owned, which is the intended safety net rather than an inconvenience.
    """
    async with _require_pool().acquire() as conn:
        yield conn


@contextlib.asynccontextmanager
async def listen_connection() -> AsyncIterator[asyncpg.Connection]:
    """One long-lived connection for LISTEN.

    Held out of the pool for the life of the process, so db_pool_max must be at
    least two. A transaction-pooled connection cannot LISTEN at all, which is why
    deployment points the API at the session pooler (docs/sales/01 § 6).
    """
    pool = _require_pool()
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


async def healthcheck() -> dict[str, Any]:
    async with system_session() as conn:
        await conn.fetchval("select 1")
    return {"database": "ok"}
