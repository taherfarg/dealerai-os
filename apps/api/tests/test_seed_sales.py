"""The local seed must be safe to run again and again, and never anywhere else."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dealerai.db.session import tenant_session
from dealerai.sales.scoring import from_stored, score
from dealerai.scripts import seed_sales
from dealerai.scripts.seed_sales import CHANNEL, CUSTOMERS, PEOPLE, TENANT, person_id, seed


async def test_the_seed_can_run_twice(db: None) -> None:
    assert await seed() == 0
    assert await seed() == 0, "a second run must replace the workspace, not collide with it"
    async with tenant_session(TENANT) as conn:
        assert await conn.fetchval("select count(*) from memberships") == len(PEOPLE)
        # One more than the customers: the duplicate the merge dialog needs.
        assert await conn.fetchval("select count(*) from contacts") == len(CUSTOMERS) + 1
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


async def test_the_seeded_board_has_somewhere_to_start_and_somewhere_to_finish(
    db: None,
) -> None:
    """The board is the demo too: a column with nothing in it teaches nobody
    anything, and a board with no won or lost lead hides half the screen."""
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        boards = await conn.fetch(
            """select p.name, count(s.id) as stages from pipelines p
                 join pipeline_stages s on s.pipeline_id = p.id
                where p.tenant_id = $1 group by p.name, p.position order by p.position""",
            TENANT,
        )
        assert [row["name"] for row in boards] == ["Local sale", "Export"]

        by_category = dict(
            await conn.fetch(
                """select s.category, count(*) from leads l
                     join pipeline_stages s on s.id = l.stage_id
                    group by s.category"""
            )
        )
        assert by_category["won"] == 1
        assert by_category["lost"] == 1
        assert by_category["open"] >= 3, "most columns should have something in them"

        lost = await conn.fetchrow(
            """select l.lost_reason from leads l join pipeline_stages s on s.id = l.stage_id
                where s.category = 'lost'"""
        )
        assert lost is not None and lost["lost_reason"], (
            "a lost lead without a reason teaches nothing"
        )

        # The score on a lead has to agree with the signals the drawer explains
        # it with, or the screen argues with itself.
        # The pool decodes jsonb, so score_signals arrives as a list already.
        leads = await conn.fetch("select score, score_signals from leads where score is not null")
        for lead in leads:
            total, _, _ = score(from_stored(lead["score_signals"]))
            assert total == lead["score"]


async def test_the_seeded_day_has_something_late_in_it(db: None) -> None:
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        buckets = await conn.fetchrow(
            """select count(*) filter (where status = 'open' and due_at < now())   as overdue,
                      count(*) filter (where status = 'open' and due_at >= now()
                                         and due_at < now() + interval '1 day')    as soon,
                      count(*) filter (where status = 'open'
                                         and due_at >= now() + interval '1 day')   as later,
                      count(*) filter (where status = 'done')                      as done
                 from tasks"""
        )
        assert buckets is not None
        assert (buckets["overdue"], buckets["soon"], buckets["later"], buckets["done"]) == (
            1,
            1,
            1,
            1,
        )


async def test_a_duplicate_customer_is_waiting_to_be_merged(db: None) -> None:
    """The merge dialog needs two records of one person to be worth opening."""
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        assert (
            await conn.fetchval(
                "select count(*) from contacts where full_name = 'Omar Al Mazrouei'"
            )
            == 2
        )


async def test_the_panel_can_show_both_markers_the_first_time_it_opens(db: None) -> None:
    """One customer with an AI value that points at a message, and a human one."""
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        profile = await conn.fetchval(
            """select profile from contacts
                where full_name = 'Omar Al Mazrouei' and profile <> '{}'::jsonb limit 1"""
        )
    assert profile["purchase_type"]["source"] == "human"
    assert profile["interest"]["source"] == "ai"
    assert profile["interest"]["evidence_message_id"], (
        "an AI value with no evidence explains nothing"
    )


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
