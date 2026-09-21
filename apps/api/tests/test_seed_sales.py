"""The local seed must be safe to run again and again, and never anywhere else."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dealerai.db.session import tenant_session
from dealerai.scripts import seed_sales
from dealerai.scripts.seed_sales import CHANNEL, CUSTOMERS, PEOPLE, TENANT, person_id, seed


async def test_the_seed_can_run_twice(db: None) -> None:
    assert await seed() == 0
    assert await seed() == 0, "a second run must replace the workspace, not collide with it"
    async with tenant_session(TENANT) as conn:
        assert await conn.fetchval("select count(*) from memberships") == len(PEOPLE)
        assert await conn.fetchval("select count(*) from contacts") == len(CUSTOMERS)
        assert await conn.fetchval("select count(*) from conversations") == len(CUSTOMERS)
        assert await conn.fetchval("select count(*) from message_templates") == 3
        assert await conn.fetchval("select external_id from channels where id=$1", CHANNEL)
        empty = await conn.fetchval(
            """select count(*) from conversations cv
               where not exists (select 1 from messages m where m.conversation_id = cv.id)"""
        )
        assert empty == 0, "a conversation with nothing in it is not worth opening"


async def test_the_seeded_queue_looks_like_a_monday_morning(db: None) -> None:
    """The seed is the demo, so its shape is part of what works.

    One customer already missed, one next in line, one nobody has taken, one
    answered, one closed, one voice note with its transcript — and two people
    who do not see the same unread counts. Flattening any of that takes the
    first screen anyone sees with it.
    """
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        # Ordered by how long they have waited, so the clock cannot make this flaky.
        waiting = await conn.fetch(
            """select c.full_name from conversations cv join contacts c on c.id = cv.contact_id
               where cv.waiting_since is not null order by cv.waiting_since"""
        )
        assert [row["full_name"] for row in waiting] == [
            "Omar Al Mazrouei",
            "Mona Fathy",
            "James Whitfield",
        ]
        assert (
            await conn.fetchval("select count(*) from conversations where sla_due_at < now()") == 1
        )
        assert (
            await conn.fetchval(
                "select count(*) from conversations where assigned_to is null and status = 'open'"
            )
            == 1
        )
        assert (
            await conn.fetchval("select count(*) from conversations where status = 'closed'") == 1
        )
        assert (
            await conn.fetchval(
                """select count(*) from messages
                   where type = 'audio' and coalesce(transcript->>'text', '') <> ''
                     and media->0->>'status' = 'ready'"""
            )
            == 1
        )
        # Per conversation, not totalled: two people can be owed the same number
        # of replies and still be looking at completely different rows.
        unread = """
            select c.full_name,
                   (select count(*) from messages m
                     where m.conversation_id = cv.id and m.direction = 'in'
                       and m.created_at > coalesce(r.last_read_at, '-infinity'::timestamptz))
              from conversations cv
              join contacts c on c.id = cv.contact_id
              left join conversation_reads r
                on r.conversation_id = cv.id and r.user_id = $1"""
        ahmed = {row[0]: row[1] for row in await conn.fetch(unread, person_id("Ahmed Nasser"))}
        sara = {row[0]: row[1] for row in await conn.fetch(unread, person_id("Sara Mansour"))}
        assert sara["Omar Al Mazrouei"] == 0 and ahmed["Omar Al Mazrouei"] > 0
        assert sara["Mona Fathy"] > ahmed["Mona Fathy"] > 0


async def test_visibility_holds_on_the_seeded_workspace(db: None) -> None:
    assert await seed() == 0
    ahmed = person_id("Ahmed Nasser")
    async with tenant_session(TENANT, user_id=ahmed, scope="own") as conn:
        his = await conn.fetchval("select count(*) from contacts")
    assert 0 < his < len(CUSTOMERS), "a salesperson should see some customers, not all"


async def test_the_seed_refuses_to_run_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        seed_sales,
        "get_settings",
        lambda: SimpleNamespace(env="staging", migration_dsn="postgresql://never@nowhere/db"),
    )
    assert await seed() == 1
