"""The local seed must be safe to run again and again, and never anywhere else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import asyncpg
import pytest

from dealerai.config import get_settings
from dealerai.db.session import tenant_session
from dealerai.sales import dashboard
from dealerai.sales.scoring import from_stored, score
from dealerai.sales.settings import SalesSettings
from dealerai.scripts import seed_sales
from dealerai.scripts.seed_sales import (
    CHANNEL,
    CUSTOMERS,
    PEOPLE,
    TENANT,
    TIMEZONE,
    person_id,
    seed,
)

pytestmark = pytest.mark.usefixtures("offline_seed")


async def test_the_seed_has_copilot_examples_and_embedded_policies(db: None) -> None:
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        policies = await conn.fetch(
            """select d.title, d.status, d.storage_path, count(c.id) as chunks,
                      count(c.embedding) as embedded
                 from documents d left join doc_chunks c on c.document_id = d.id
                group by d.id order by d.title"""
        )
        assert len(policies) == 3
        assert all(row["status"] == "ready" and row["storage_path"] for row in policies)
        assert all(row["chunks"] > 0 and row["embedded"] == row["chunks"] for row in policies)

        drafts = await conn.fetch(
            """select ct.full_name, s.status, s.sources, s.blocked_reason,
                      s.confidence, cv.wa_window_expires_at
                 from ai_suggestions s
                 join conversations cv on cv.id = s.conversation_id
                 join contacts ct on ct.id = cv.contact_id"""
        )
        assert any(
            row["full_name"] == "Omar Al Mazrouei"
            and row["status"] == "ready"
            and {source["kind"] for source in row["sources"]} == {"vehicle", "document"}
            for row in drafts
        )
        assert any(row["status"] == "blocked" and row["blocked_reason"] for row in drafts)
        assert all(row["confidence"] in {"high", "medium", "low"} for row in drafts)
        assert (
            await conn.fetchval(
                """select count(*) from conversations cv
                 join contacts ct on ct.id = cv.contact_id
                where ct.full_name = 'Karim Benali' and cv.wa_window_expires_at < $1""",
                datetime.now(UTC),
            )
            == 1
        )

        assert (
            await conn.fetchval(
                """select count(*) from tasks
                where source = 'ai' and kind = 'follow_up'
                  and ai_draft->>'reason' ilike '%price%'
                  and ai_draft->>'template_name' = 'price_update'"""
            )
            == 1
        )


async def test_the_seed_runs_with_no_model_key(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """CI's end-to-end job has Postgres and nothing else. The workspace must
    seed there, policies and all, without buying a vector."""
    from dealerai.ai import embeddings, gateway

    # The real embedder, and nothing it could reach a model with.
    monkeypatch.setattr(seed_sales, "embed", embeddings.embed)
    monkeypatch.setattr(get_settings(), "google_api_key", "")
    monkeypatch.setattr(gateway, "_client", None)
    monkeypatch.setattr(gateway, "_loop_clients", {})

    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        policies = await conn.fetch(
            """select d.status, count(c.id) as chunks, count(c.embedding) as embedded
                 from documents d left join doc_chunks c on c.document_id = d.id
                group by d.id"""
        )
    assert len(policies) == 3
    assert all(row["status"] == "ready" and row["chunks"] > 0 for row in policies)
    assert all(row["embedded"] == 0 for row in policies), "a made-up vector would answer questions"


async def test_the_seed_can_run_twice(db: None) -> None:
    assert await seed() == 0
    assert await seed() == 0, "a second run must replace the workspace, not collide with it"
    async with tenant_session(TENANT) as conn:
        assert await conn.fetchval("select count(*) from memberships") == len(PEOPLE)
        # One more than the customers: the duplicate the merge dialog needs.
        assert await conn.fetchval("select count(*) from contacts") == len(CUSTOMERS) + 1
        assert await conn.fetchval("select count(*) from conversations") == len(CUSTOMERS)
        assert await conn.fetchval("select count(*) from message_templates") == 6
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
        assert by_category["won"] == 2, "one on each board"
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
            3,
            2,
            1,
            1,
        )


async def test_the_workspace_has_quick_replies(db: None) -> None:
    """Something to type `/` for on the first day, in every language the
    dealership writes in, each greeting the customer by name."""
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        rows = await conn.fetch("select shortcut, body from quick_replies")
    assert {row["shortcut"] for row in rows} == {"/price", "/location", "/documents"}
    for row in rows:
        assert set(row["body"]) == {"ar", "en", "fr"}
        assert all("{name}" in text for text in row["body"].values())


async def test_yesterday_has_a_first_response_a_miss_and_a_win(db: None) -> None:
    """The morning brief is about yesterday, so the seed has one — counted by
    the dashboard's own functions, which are what the brief reads."""
    assert await seed() == 0
    now = datetime.now(UTC)
    tz = ZoneInfo(TIMEZONE)
    since, until = dashboard.day_window(now.astimezone(tz).date() - timedelta(days=1), tz)
    async with tenant_session(TENANT) as conn:
        settings = SalesSettings.model_validate(
            await conn.fetchval("select sales_settings from tenants where id = $1", TENANT)
        )
        waits = await dashboard.answered(conn, since, until, tz=tz, settings=settings)
        facts = await dashboard.facts(conn, since, until, now, waits, settings)
        missed_by = await conn.fetchval(
            "select assigned_to from sla_misses where due_at >= $1 and due_at < $2", since, until
        )
        won_on = await conn.fetchval(
            """select p.name from leads l
                 join pipeline_stages s on s.id = l.stage_id
                 join pipelines p on p.id = l.pipeline_id
                where s.category = 'won' and l.stage_entered_at >= $1
                  and l.stage_entered_at < $2""",
            since,
            until,
        )
        items = await dashboard.attention(conn, now)

    assert facts["new_conversations"] == 4
    median = dashboard.median_of(waits)
    assert median is not None and 2 * 60 <= median <= 9 * 60, "a median worth reading"
    assert facts["missed_targets"] == 1 and missed_by == person_id("Salem Bousaid")
    assert facts["won"] == 1 and won_on == "Local sale"
    # What the brief puts in front of a manager: somebody waiting, a hot lead
    # nobody is working, and whoever has the most tasks past due.
    assert {item["kind"] for item in items} == {"waiting", "hot_lead", "overdue_tasks"}
    overdue = next(item for item in items if item["kind"] == "overdue_tasks")
    assert overdue["name"] == "Mohamed Riad"


async def test_todays_brief_is_queued_once_however_often_the_seed_runs(
    db: None, su: asyncpg.Connection
) -> None:
    """A running worker writes it through the real handler; the seed only asks."""
    assert await seed() == 0
    assert await seed() == 0
    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    rows = await su.fetch(
        """select dedupe_key, status, run_after from events
            where tenant_id = $1 and event_type = 'sales.brief_due'""",
        TENANT,
    )
    assert [(row["dedupe_key"], row["status"]) for row in rows] == [(f"brief:{today}", "pending")]
    assert rows[0]["run_after"] <= datetime.now(UTC)


async def test_a_seeded_wait_has_its_check_booked_as_a_real_one_does(
    db: None, su: asyncpg.Connection
) -> None:
    """Otherwise a customer turns red on screen and the miss is never counted.
    James's warning is still ahead; Mona's has passed, so the miss it would have
    booked is; Omar's miss already happened and is a row."""
    assert await seed() == 0
    booked = await su.fetch(
        """select c.full_name, e.payload->>'level' as level
             from events e
             join conversations cv on cv.id = (e.payload->>'conversation_id')::uuid
             join contacts c on c.id = cv.contact_id
            where e.event_type = 'conversation.sla_check' and e.status = 'pending'"""
    )
    assert {row["full_name"]: row["level"] for row in booked} == {
        "James Whitfield": "due_soon",
        "Mona Fathy": "missed",
    }


async def test_a_customer_no_rule_routes_lands_where_a_manager_sees_them(db: None) -> None:
    """With no default team a new customer has no team, and only the owner sees
    them: the exit run's new customer never reached Sara's dashboard."""
    assert await seed() == 0
    async with tenant_session(TENANT) as conn:
        team = await conn.fetchval(
            """select t.name from tenants tn
                 join teams t on t.id = (tn.sales_settings->>'default_team_id')::uuid
                where tn.id = $1""",
            TENANT,
        )
    assert team == "Local sales"


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
