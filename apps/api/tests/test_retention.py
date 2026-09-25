"""The nightly retention pass: data that forgets itself on time."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg

from conftest import TENANT_A, TENANT_B, USER_A
from dealerai.events.bus import Event
from dealerai.events.handlers.privacy import on_retention_due

NOW = datetime.now(UTC)
#: Past the 24-month default by a month.
LONG_AGO = NOW - timedelta(days=31 * 25)


async def _run(tenant_id: uuid.UUID = TENANT_A) -> None:
    await on_retention_due(
        Event(1, tenant_id, "sales.retention_due", {"date": "2026-09-25"}, 1, None)
    )


async def _age(
    su: asyncpg.Connection,
    tenant_id: uuid.UUID,
    *,
    seen: datetime,
    last_message: datetime | None = None,
) -> uuid.UUID:
    """The tenant's fixture customer, last seen at `seen`, their conversation
    last active at `last_message` — the same moment unless said otherwise."""
    contact: uuid.UUID = await su.fetchval(
        "select id from contacts where tenant_id = $1", tenant_id
    )
    await su.execute("update contacts set last_seen_at = $2 where id = $1", contact, seen)
    await su.execute(
        "update conversations set last_message_at = $2 where contact_id = $1",
        contact,
        last_message or seen,
    )
    return contact


async def _exists(su: asyncpg.Connection, contact: uuid.UUID) -> bool:
    return bool(await su.fetchval("select count(*) from contacts where id = $1", contact))


async def test_a_customer_silent_past_the_retention_period_is_erased(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact = await _age(su, TENANT_A, seen=LONG_AGO)
    await _run()
    assert not await _exists(su, contact)
    row = await su.fetchrow(
        """select actor_type, meta from audit_log
            where action = 'contact.erased' and entity_id = $1""",
        contact,
    )
    assert row["actor_type"] == "system"
    assert json.loads(row["meta"]) == {"reason": "retention"}


async def test_a_customer_who_wrote_last_month_stays(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact = await _age(su, TENANT_A, seen=NOW - timedelta(days=30))
    await _run()
    assert await _exists(su, contact)


async def test_one_recent_message_keeps_a_customer_we_last_saw_long_ago(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact = await _age(su, TENANT_A, seen=LONG_AGO, last_message=NOW - timedelta(days=1))
    await _run()
    assert await _exists(su, contact)


async def test_a_dealership_can_keep_less(db: None, su: asyncpg.Connection, seeded: None) -> None:
    await su.execute(
        """update tenants set sales_settings = '{"retention_months": 6}' where id = $1""",
        TENANT_A,
    )
    contact = await _age(su, TENANT_A, seen=NOW - timedelta(days=7 * 31))
    await _run()
    assert not await _exists(su, contact)


async def test_old_notifications_and_briefs_go_and_recent_ones_stay(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    for age in (91, 1):
        await su.execute(
            """insert into notifications (tenant_id, user_id, kind, title, created_at)
               values ($1, $2, 'assigned', $3, now() - make_interval(days => $4))""",
            TENANT_A,
            USER_A,
            f"{age} days old",
            age,
        )
        await su.execute(
            """insert into sales_briefs (tenant_id, user_id, brief_date, facts, created_at)
               values ($1, $2, current_date - $3::int, '{}', now() - make_interval(days => $3))""",
            TENANT_A,
            USER_A,
            age,
        )
    await _run()
    titles = [
        row["title"]
        for row in await su.fetch("select title from notifications where tenant_id = $1", TENANT_A)
    ]
    assert titles == ["1 days old"]
    briefs = await su.fetchval("select count(*) from sales_briefs where tenant_id = $1", TENANT_A)
    assert briefs == 1


async def test_raw_webhook_bodies_go_after_fourteen_days(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """They hold message text and phone numbers, and an erasure cannot find them."""
    old, recent = [
        await su.fetchval(
            """insert into webhook_deliveries (platform, signature_ok, received_at)
               values ('whatsapp', true, now() - make_interval(days => $1)) returning id""",
            age,
        )
        for age in (15, 1)
    ]
    await _run()
    kept = {
        row["id"]
        for row in await su.fetch(
            "select id from webhook_deliveries where id = any($1::bigint[])", [old, recent]
        )
    }
    assert kept == {recent}


async def test_the_other_dealership_is_untouched(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    beta = await _age(su, TENANT_B, seen=LONG_AGO)
    await _run(TENANT_A)
    assert await _exists(su, beta)


async def test_an_erased_customers_files_are_queued(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact = await _age(su, TENANT_A, seen=LONG_AGO)
    path = f"{TENANT_A}/messages/2024/01/old.jpg"
    await su.execute(
        """update messages set media = $2::jsonb
            where conversation_id in (select id from conversations where contact_id = $1)""",
        contact,
        json.dumps([{"status": "ready", "storage_path": path}]),
    )
    await _run()
    rows = await su.fetch(
        """select payload from events
            where tenant_id = $1 and event_type = 'media.delete' and status = 'pending'""",
        TENANT_A,
    )
    assert [json.loads(row["payload"])["paths"] for row in rows] == [[path]]
