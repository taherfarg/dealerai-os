"""A waiting customer has a due time in business hours, and it stops when we reply."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from conftest import MANAGER, SALES_1, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.events.bus import Event
from dealerai.events.handlers import inbox

CHANNEL = uuid.UUID("cccccccc-5555-4555-8555-000000000001")


async def _waiting_conversation(
    su: asyncpg.Connection,
    *,
    assigned_to: uuid.UUID | None,
    waiting_for: timedelta = timedelta(minutes=40),
) -> tuple[uuid.UUID, datetime]:
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'sla-phone', 'sla-waba', 'cloud_api')
           on conflict (platform, external_id) do nothing""",
        CHANNEL,
        TENANT_A,
    )
    contact_id = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Karim Benali') returning id",
        TENANT_A,
    )
    waiting_since = datetime.now(UTC) - waiting_for
    conversation_id = await su.fetchval(
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, team_id, assigned_to, owner_id,
              waiting_since, sla_due_at)
           values ($1, $2, $3, 'whatsapp', $4, $5, $5,
                   $6::timestamptz, $6::timestamptz + interval '5 minutes')
           returning id""",
        TENANT_A,
        contact_id,
        CHANNEL,
        TEAM_LOCAL,
        assigned_to,
        waiting_since,
    )
    return conversation_id, waiting_since


def _check(conversation_id: uuid.UUID, *, level: str, waiting_since: datetime) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="conversation.sla_check",
        payload={
            "conversation_id": str(conversation_id),
            "level": level,
            "waiting_since": waiting_since.isoformat(),
        },
        attempts=1,
        dedupe_key=f"sla:{conversation_id}:{level}",
    )


@pytest.fixture
async def workspace(su: asyncpg.Connection) -> asyncpg.Connection:
    await reseed_with_people()
    return su


async def test_due_soon_then_missed_notifies_once_each(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)

    await inbox.on_sla_check(_check(conversation_id, level="due_soon", waiting_since=waiting_since))
    await inbox.on_sla_check(_check(conversation_id, level="due_soon", waiting_since=waiting_since))
    await inbox.on_sla_check(_check(conversation_id, level="missed", waiting_since=waiting_since))

    told = [
        (r["kind"], r["user_id"])
        for r in await su.fetch("select kind, user_id from notifications order by created_at")
    ]
    # The rep is warned once and told once; the manager hears only the miss.
    assert told == [
        ("waiting_due_soon", SALES_1),
        ("waiting_missed", SALES_1),
        ("waiting_missed", MANAGER),
    ]


async def test_a_missed_target_also_reaches_the_manager(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)

    await inbox.on_sla_check(_check(conversation_id, level="missed", waiting_since=waiting_since))

    recipients = {r["user_id"] for r in await su.fetch("select user_id from notifications")}
    assert recipients == {SALES_1, MANAGER}


async def test_a_reply_stops_the_timer(db: None, workspace: asyncpg.Connection) -> None:
    """The salesperson answered: a check that fires later must say nothing."""
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)
    await su.execute(
        """update conversations set waiting_since = null, sla_due_at = null,
                                    first_response_at = now() where id = $1""",
        conversation_id,
    )

    await inbox.on_sla_check(_check(conversation_id, level="missed", waiting_since=waiting_since))

    assert await su.fetchval("select count(*) from notifications") == 0


async def test_a_check_from_an_older_waiting_period_says_nothing(
    db: None, workspace: asyncpg.Connection
) -> None:
    """Answered, then asked again: the new wait has its own checks."""
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)

    await inbox.on_sla_check(
        _check(conversation_id, level="missed", waiting_since=waiting_since - timedelta(hours=3))
    )

    assert await su.fetchval("select count(*) from notifications") == 0


async def test_an_unassigned_customer_is_the_managers_problem(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=None)

    await inbox.on_sla_check(_check(conversation_id, level="missed", waiting_since=waiting_since))

    rows = await su.fetch("select user_id, kind from notifications")
    assert [(r["user_id"], r["kind"]) for r in rows] == [(MANAGER, "unassigned_waiting")]


async def test_the_due_soon_check_schedules_the_missed_one(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)

    await inbox.on_sla_check(_check(conversation_id, level="due_soon", waiting_since=waiting_since))

    [scheduled] = await su.fetch(
        """select payload, run_after from events
           where event_type = 'conversation.sla_check' and status = 'pending'"""
    )
    assert "missed" in scheduled["payload"]


async def test_a_missed_target_leaves_one_row_that_outlives_its_notifications(
    db: None, workspace: asyncpg.Connection
) -> None:
    """The dashboard counts misses per day and per person. A notification is
    somebody's, and is deleted after 90 days or with its reader."""
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)

    await inbox.on_sla_check(_check(conversation_id, level="missed", waiting_since=waiting_since))
    await inbox.on_sla_check(_check(conversation_id, level="missed", waiting_since=waiting_since))
    await su.execute("delete from notifications")

    misses = await su.fetch(
        "select assigned_to, waiting_since, due_at from sla_misses where conversation_id = $1",
        conversation_id,
    )
    assert [(m["assigned_to"], m["due_at"] - m["waiting_since"]) for m in misses] == [
        (SALES_1, timedelta(minutes=5))
    ]


async def test_a_warning_is_not_a_miss(db: None, workspace: asyncpg.Connection) -> None:
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)
    await inbox.on_sla_check(_check(conversation_id, level="due_soon", waiting_since=waiting_since))
    assert await su.fetchval("select count(*) from sla_misses") == 0


async def test_an_answered_customer_leaves_no_miss(db: None, workspace: asyncpg.Connection) -> None:
    su = workspace
    conversation_id, waiting_since = await _waiting_conversation(su, assigned_to=SALES_1)
    await su.execute(
        """update conversations set waiting_since = null, sla_due_at = null,
                                    first_response_at = now() where id = $1""",
        conversation_id,
    )
    await inbox.on_sla_check(_check(conversation_id, level="missed", waiting_since=waiting_since))
    assert await su.fetchval("select count(*) from sla_misses") == 0
