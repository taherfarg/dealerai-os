"""Every dealership's own 08:00 and 03:00.

The brief is at eight in the morning where the showroom is and retention at
three at night, so neither can be one global schedule. Each tenant's next run
is an event whose `run_after` is that tenant's local hour. Once an hour the
worker asks app.tenant_clocks() — the one cross-tenant read, ids and timezones
only — and schedules whatever is not already scheduled. The dedupe key is the
local date, so a pass that finds tomorrow's run waiting adds nothing, and a
chain an outage broke is back on time within the hour.

ponytail: an hourly pass in the worker rather than a scheduler process. Upgrade
trigger: a job that needs minute precision with no event to hang it on.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ..db.session import system_session
from ..events.bus import emit

BRIEF_AT = time(8, 0)
RETENTION_AT = time(3, 0)


def zone(name: str | None) -> ZoneInfo:
    """A tenant's timezone, or UTC when the name means nothing: a typo in one
    tenant's settings must not stop the clock (routes/tasks.day_start)."""
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001 - ZoneInfo raises several types for a bad key
        return ZoneInfo("UTC")


def next_at(at: time, tz: ZoneInfo, now: datetime) -> datetime:
    """The next instant the local clock reads `at`: today if still ahead, else tomorrow."""
    local = now.astimezone(tz)
    today = local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if today > local:
        return today.astimezone(UTC)
    tomorrow = (local + timedelta(days=1)).replace(
        hour=at.hour, minute=at.minute, second=0, microsecond=0
    )
    return tomorrow.astimezone(UTC)


async def schedule(conn: Any, tenant_id: UUID, tz: ZoneInfo, now: datetime) -> None:
    """One tenant's next brief and next retention pass, unless already scheduled."""
    brief = next_at(BRIEF_AT, tz, now)
    brief_day = brief.astimezone(tz).date().isoformat()
    await emit(
        conn,
        "sales.brief_due",
        {"date": brief_day},
        tenant_id=tenant_id,
        dedupe_key=f"brief:{brief_day}",
        run_after=brief,
        priority=1,
    )
    sweep = next_at(RETENTION_AT, tz, now)
    sweep_day = sweep.astimezone(tz).date().isoformat()
    await emit(
        conn,
        "sales.retention_due",
        {"date": sweep_day},
        tenant_id=tenant_id,
        dedupe_key=f"retention:{sweep_day}",
        run_after=sweep,
    )


async def schedule_everyone(now: datetime | None = None) -> int:
    """One pass over every active tenant; returns how many it saw.

    `events` has no RLS (it is isolated by GRANT), so a session with no tenant
    may write to it — the claim loop does the same.
    """
    moment = now or datetime.now(UTC)
    async with system_session() as conn:
        tenants = await conn.fetch("select id, timezone from app.tenant_clocks()")
        for tenant in tenants:
            await schedule(conn, tenant["id"], zone(tenant["timezone"]), moment)
    return len(tenants)
