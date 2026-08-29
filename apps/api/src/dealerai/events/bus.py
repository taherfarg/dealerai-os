"""The event bus: emit, and the handler registry.

The `events` table is the queue, the outbox, and the audit trail of intent all
at once. See docs/01-system-architecture.md § 3 for why that is one table and
not three, and why there is no Redis yet.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
import structlog

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class Event:
    id: int
    tenant_id: UUID | None
    event_type: str
    payload: dict[str, Any]
    attempts: int
    dedupe_key: str | None


Handler = Callable[[Event], Awaitable[None]]

_HANDLERS: dict[str, Handler] = {}


class UnknownEventType(Exception):
    """Raised when no handler is registered.

    Deliberately a normal failure rather than an immediate dead-letter: during a
    rolling deploy an old worker can briefly see an event type it does not know,
    and a few minutes of backoff lets a new worker pick it up. A genuinely
    unknown type still dead-letters once max_attempts runs out.
    """


def register(event_type: str, fn: Handler) -> None:
    if event_type in _HANDLERS:
        raise ValueError(f"handler for {event_type!r} already registered")
    _HANDLERS[event_type] = fn


def handler(event_type: str) -> Callable[[Handler], Handler]:
    def decorate(fn: Handler) -> Handler:
        register(event_type, fn)
        return fn

    return decorate


def get_handler(event_type: str) -> Handler | None:
    return _HANDLERS.get(event_type)


def registered_types() -> frozenset[str]:
    return frozenset(_HANDLERS)


_INSERT = """
insert into events (tenant_id, event_type, payload, dedupe_key, priority, run_after)
values ($1, $2, $3, $4, $5, coalesce($6, now()))
on conflict do nothing
returning id
"""


async def emit(
    conn: asyncpg.Connection,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    tenant_id: UUID | None = None,
    dedupe_key: str | None = None,
    run_after: datetime | None = None,
    priority: int = 0,
) -> int | None:
    """Enqueue an event **on the caller's connection**.

    Taking the connection rather than grabbing its own is the whole point: the
    event and the row that caused it commit together. An event emitted on a
    separate connection can survive a rolled-back transaction, which produces a
    job for a vehicle that was never created.

    Returns the new event id, or None when a pending event with the same
    dedupe_key already exists.
    """
    row = await conn.fetchrow(
        _INSERT, tenant_id, event_type, payload or {}, dedupe_key, priority, run_after
    )
    if row is None:
        log.debug("event_deduped", event_type=event_type, dedupe_key=dedupe_key)
        return None
    return int(row["id"])
