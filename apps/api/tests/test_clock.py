"""Every dealership's own 08:00 and 03:00."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B
from dealerai import worker
from dealerai.sales import clock
from dealerai.sales.clock import BRIEF_AT, RETENTION_AT, next_at, schedule_everyone, zone

DUBAI = ZoneInfo("Asia/Dubai")


def test_the_brief_is_at_eight_where_the_showroom_is() -> None:
    seven_in_dubai = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
    assert next_at(BRIEF_AT, DUBAI, seven_in_dubai) == datetime(2026, 9, 24, 4, 0, tzinfo=UTC)


def test_after_eight_it_is_tomorrows() -> None:
    nine_in_dubai = datetime(2026, 9, 24, 5, 0, tzinfo=UTC)
    assert next_at(BRIEF_AT, DUBAI, nine_in_dubai) == datetime(2026, 9, 25, 4, 0, tzinfo=UTC)


def test_retention_runs_at_three_in_the_morning() -> None:
    midnight_in_dubai = datetime(2026, 9, 23, 20, 0, tzinfo=UTC)
    assert next_at(RETENTION_AT, DUBAI, midnight_in_dubai) == datetime(
        2026, 9, 23, 23, 0, tzinfo=UTC
    )


def test_a_timezone_nobody_knows_is_utc_rather_than_a_stopped_clock() -> None:
    assert zone("Mars/Olympus") == ZoneInfo("UTC")
    assert zone(None) == ZoneInfo("UTC")


async def _scheduled(su: asyncpg.Connection) -> list[asyncpg.Record]:
    return list(
        await su.fetch(
            """select tenant_id, event_type, payload->>'date' as day, run_after from events
                where event_type in ('sales.brief_due', 'sales.retention_due')
                  and status = 'pending'
                order by tenant_id, event_type"""
        )
    )


async def test_a_pass_schedules_each_tenant_once_however_often_it_runs(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    now = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
    assert await schedule_everyone(now) == 2
    await schedule_everyone(now)
    rows = await _scheduled(su)
    assert [(row["tenant_id"], row["event_type"]) for row in rows] == [
        (TENANT_A, "sales.brief_due"),
        (TENANT_A, "sales.retention_due"),
        (TENANT_B, "sales.brief_due"),
        (TENANT_B, "sales.retention_due"),
    ]
    brief = rows[0]
    assert (brief["day"], brief["run_after"]) == (
        "2026-09-24",
        datetime(2026, 9, 24, 4, 0, tzinfo=UTC),
    )


async def test_once_a_brief_has_run_the_next_pass_schedules_tomorrows(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await schedule_everyone(datetime(2026, 9, 24, 3, 0, tzinfo=UTC))
    await su.execute("update events set status = 'done' where event_type = 'sales.brief_due'")
    await schedule_everyone(datetime(2026, 9, 24, 4, 5, tzinfo=UTC))
    days = {row["day"] for row in await _scheduled(su) if row["event_type"] == "sales.brief_due"}
    assert days == {"2026-09-25"}


async def test_a_paused_dealership_gets_no_brief(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await su.execute("update tenants set status = 'paused' where id = $1", TENANT_B)
    assert await schedule_everyone(datetime(2026, 9, 24, 3, 0, tzinfo=UTC)) == 1


async def test_the_worker_keeps_the_clocks_through_a_failed_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    calls: list[int] = []

    async def flaky(now: datetime | None = None) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database away")
        stop.set()
        return 0

    monkeypatch.setattr(clock, "schedule_everyone", flaky)
    monkeypatch.setattr(worker, "CLOCK_EVERY_SECONDS", 0)
    await asyncio.wait_for(worker.keep_the_clocks(stop), timeout=5)
    assert len(calls) == 2
