"""Claim loop, retries, dead-lettering, and the stuck-job reaper."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog

from ..db.session import system_session
from .bus import Event, UnknownEventType, get_handler

log = structlog.get_logger()

DEFAULT_BATCH = 20
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_LOCK_TIMEOUT_MINUTES = 15
#: Cap the backoff exponent so a long-lived failure does not schedule a retry
#: seventeen days out.
MAX_BACKOFF_EXPONENT = 10

_CLAIM = """
update events set
    status    = 'processing',
    locked_at = now(),
    locked_by = $1,
    attempts  = attempts + 1
where id in (
    select id from events
    where status = 'pending' and run_after <= now()
    order by priority desc, id
    limit $2
    for update skip locked
)
returning id, tenant_id, event_type, payload, attempts, dedupe_key, priority
"""

_DONE = """
update events set status = 'done', processed_at = now(), error = null,
                  locked_at = null, locked_by = null
where id = $1
"""

# One statement decides retry-or-dead-letter, so two workers cannot disagree.
_FAIL = """
update events set
    status      = case when attempts >= max_attempts then 'failed' else 'pending' end,
    dead_letter = attempts >= max_attempts,
    error       = $2,
    run_after   = now() + (interval '1 minute' * power(2, least(attempts, $3))),
    locked_at   = null,
    locked_by   = null
where id = $1
returning status, dead_letter, run_after
"""

_REAP = """
update events set status = 'pending', locked_at = null, locked_by = null
where status = 'processing' and locked_at < now() - make_interval(mins => $1)
returning id
"""


def _to_event(row: Any) -> Event:
    return Event(
        id=row["id"],
        tenant_id=row["tenant_id"],
        event_type=row["event_type"],
        payload=row["payload"] or {},
        attempts=row["attempts"],
        dedupe_key=row["dedupe_key"],
    )


class Worker:
    def __init__(
        self,
        name: str,
        *,
        batch_size: int = DEFAULT_BATCH,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        lock_timeout_minutes: int = DEFAULT_LOCK_TIMEOUT_MINUTES,
    ) -> None:
        self.name = name
        self.batch_size = batch_size
        self.poll_seconds = poll_seconds
        self.lock_timeout_minutes = lock_timeout_minutes

    async def claim(self) -> list[Event]:
        """Read the queue with no tenant context.

        This is the one legitimate cross-tenant read in the system — the tenant
        is not known until the row comes back. `events` therefore has no RLS and
        is isolated by GRANT instead; see docs/03-database-schema.md § 2.
        """
        async with system_session() as conn:
            rows = await conn.fetch(_CLAIM, self.name, self.batch_size)
        # UPDATE ... RETURNING does not preserve the sub-select's ORDER BY, so
        # re-sort here. Without this, priority decides *which* events are
        # claimed but not the order they run in — and a customer reply ends up
        # behind nineteen metric fetches in the same batch.
        rows.sort(key=lambda r: (-r["priority"], r["id"]))
        return [_to_event(r) for r in rows]

    async def dispatch(self, event: Event) -> None:
        fn = get_handler(event.event_type)
        if fn is None:
            raise UnknownEventType(event.event_type)
        await fn(event)

    async def process(self, event: Event) -> bool:
        """Run one event's handler. Returns True on success.

        No transaction is held while the handler runs. Handlers make model calls
        that take tens of seconds, and holding a transaction across those would
        exhaust the pool and pin XIDs. The cost is at-least-once delivery, which
        is why handlers must be idempotent.
        """
        bound = log.bind(
            event_id=event.id,
            event_type=event.event_type,
            tenant_id=str(event.tenant_id) if event.tenant_id else None,
            attempt=event.attempts,
            worker=self.name,
        )
        try:
            await self.dispatch(event)
        except Exception as exc:
            async with system_session() as conn:
                row = await conn.fetchrow(
                    _FAIL, event.id, f"{type(exc).__name__}: {exc}"[:2000], MAX_BACKOFF_EXPONENT
                )
            if row is not None and row["dead_letter"]:
                bound.error("event_dead_lettered", error=str(exc))
            else:
                bound.warning("event_retrying", error=str(exc), retry_at=row and row["run_after"])
            return False

        async with system_session() as conn:
            await conn.execute(_DONE, event.id)
        bound.info("event_done")
        return True

    async def run_once(self) -> int:
        """Claim and process one batch. Returns how many events were claimed.

        Split out from the loop so tests are deterministic — they never sleep.
        """
        events = await self.claim()
        for event in events:
            await self.process(event)
        return len(events)

    async def reap(self) -> list[int]:
        """Release events whose worker died mid-flight.

        `attempts` was already incremented at claim time, so a worker that
        crash-loops on one event still exhausts its retries rather than spinning
        forever.
        """
        async with system_session() as conn:
            rows = await conn.fetch(_REAP, self.lock_timeout_minutes)
        ids = [int(r["id"]) for r in rows]
        if ids:
            log.warning("events_reaped", count=len(ids), worker=self.name)
        return ids

    async def run_forever(self, stop: asyncio.Event) -> None:
        reap_every = max(self.lock_timeout_minutes * 60 / 4, 30)
        next_reap = 0.0
        while not stop.is_set():
            now = asyncio.get_running_loop().time()
            if now >= next_reap:
                await self.reap()
                next_reap = now + reap_every
            try:
                claimed = await self.run_once()
            except Exception:
                # A failure here is the queue itself (connection lost, table
                # gone), not a handler. Back off rather than hot-loop.
                log.exception("worker_claim_failed", worker=self.name)
                claimed = 0
            if claimed == 0:
                # Sleep, but wake immediately on shutdown.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_seconds)
