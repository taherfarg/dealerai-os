"""My day: my numbers, my queue, my tasks, my hot leads."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.db.session import tenant_session
from dealerai.main import app
from dealerai.routes.tasks import window
from dealerai.sales import dashboard as numbers
from dealerai.sales.settings import WEEKDAYS, SalesSettings

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


def _later_today() -> datetime:
    start, end = window("today", "Asia/Dubai", datetime.now(UTC))
    assert start is not None and end is not None
    return start + (end - start) / 2


async def _conversation(
    conn: asyncpg.Connection, name: str, *, owner: uuid.UUID, waiting_minutes: int | None
) -> uuid.UUID:
    contact = await conn.fetchval(
        """insert into contacts (tenant_id, full_name, owner_id, team_id)
           values ($1, $2, $3, $4) returning id""",
        TENANT_A,
        name,
        owner,
        TEAM_LOCAL,
    )
    waiting_since = NOW - timedelta(minutes=waiting_minutes) if waiting_minutes else None
    return uuid.UUID(  # type: ignore[no-any-return]
        str(
            await conn.fetchval(
                """insert into conversations (tenant_id, contact_id, surface, status, owner_id,
                                              team_id, assigned_to, waiting_since, sla_due_at,
                                              last_message_at)
                   values ($1, $2, 'whatsapp', 'open', $3, $4, $3, $5::timestamptz,
                           $5::timestamptz + interval '5 minutes', coalesce($5::timestamptz, now()))
                   returning id""",
                TENANT_A,
                contact,
                owner,
                TEAM_LOCAL,
                waiting_since,
            )
        )
    )


async def _seed() -> None:
    """Sales1's morning: two people waiting, one answered, a task and a hot lead."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("update tenants set timezone = 'Asia/Dubai' where id = $1", TENANT_A)
        await _conversation(conn, "Omar Al Mazrouei", owner=SALES_1, waiting_minutes=40)
        await _conversation(conn, "James Whitfield", owner=SALES_1, waiting_minutes=5)
        answered = await _conversation(conn, "Mona Fathy", owner=SALES_1, waiting_minutes=None)
        await _conversation(conn, "Someone else's", owner=SALES_2, waiting_minutes=90)

        # Answered nine minutes after she wrote, this morning.
        asked_at = NOW - timedelta(minutes=30)
        await conn.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, body,
                                     created_at)
               values ($1, $2, 'in', 'customer', 'customer', 'Is it available?', $3)""",
            TENANT_A,
            answered,
            asked_at,
        )
        await conn.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                     author_user_id, body, created_at)
               values ($1, $2, 'out', 'human', 'inbox', $3, 'Yes, it is.', $4)""",
            TENANT_A,
            answered,
            SALES_1,
            asked_at + timedelta(minutes=9),
        )
        await conn.execute(
            "update conversations set first_response_at = $2 where id = $1",
            answered,
            asked_at + timedelta(minutes=9),
        )
    finally:
        await conn.close()


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(_seed())
    with TestClient(app) as test_client:
        yield test_client


def _my_day(client: TestClient, user: uuid.UUID = SALES_1) -> dict[str, Any]:
    response = client.get("/v1/dashboard/me", headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_waiting_on_you_is_oldest_first_and_only_mine(client: TestClient) -> None:
    waiting = _my_day(client)["waiting_on_you"]
    assert [row["contact"]["name"] for row in waiting] == [
        "Omar Al Mazrouei",
        "James Whitfield",
    ], "the customer waiting longest is the one to answer first"
    assert all(row["waiting_since"] is not None for row in waiting)


def test_my_day_counts_only_my_replies(client: TestClient) -> None:
    assert _my_day(client)["replied_today"] == 1
    assert _my_day(client, MANAGER)["replied_today"] == 0


def test_the_median_first_response_is_measured_from_what_the_customer_said(
    client: TestClient,
) -> None:
    """waiting_since is cleared when the reply lands, so the number comes from
    the messages — nine minutes, not "nothing recorded"."""
    assert _my_day(client)["median_first_response_seconds"] == 9 * 60


def test_the_median_is_null_before_the_first_reply_of_the_day(client: TestClient) -> None:
    """A zero would read as instant."""
    assert _my_day(client, MANAGER)["median_first_response_seconds"] is None


def test_due_today_holds_my_tasks_soonest_first(client: TestClient) -> None:
    for title, due in (
        ("Later", _later_today()),
        ("Sooner", datetime.now(UTC) + timedelta(minutes=1)),
    ):
        response = client.post(
            "/v1/tasks", json={"title": title, "due_at": due.isoformat()}, headers=_auth(SALES_1)
        )
        assert response.status_code == 201, response.text

    assert [task["title"] for task in _my_day(client)["due_today"]] == ["Sooner", "Later"]
    assert _my_day(client, SALES_2)["due_today"] == []


def test_hot_leads_are_mine_and_hot(client: TestClient) -> None:
    asyncio.run(_leads())
    hot = _my_day(client)["hot_leads"]
    assert [lead["contact"]["name"] for lead in hot] == ["Omar Al Mazrouei"]
    assert hot[0]["band"] == "hot"


async def _leads() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        stage = await conn.fetchrow(
            """select s.id, s.pipeline_id from pipeline_stages s
                join pipelines p on p.id = s.pipeline_id
               where s.tenant_id = $1 and s.category = 'open'
               order by p.is_default desc, s.position limit 1""",
            TENANT_A,
        )
        for name, owner, band, score in (
            ("Omar Al Mazrouei", SALES_1, "hot", 80),
            ("James Whitfield", SALES_1, "warm", 45),
            ("Someone else's", SALES_2, "hot", 90),
        ):
            contact = await conn.fetchval(
                "select id from contacts where tenant_id = $1 and full_name = $2", TENANT_A, name
            )
            await conn.execute(
                """insert into leads (tenant_id, contact_id, pipeline_id, stage_id, owner_id,
                                      intent_band, score)
                   values ($1, $2, $3, $4, $5, $6, $7)""",
                TENANT_A,
                contact,
                stage["pipeline_id"],
                stage["id"],
                owner,
                band,
                score,
            )
    finally:
        await conn.close()


def test_a_deal_already_won_is_not_something_to_chase_this_morning(
    client: TestClient,
) -> None:
    """Found by winning one on the board and watching it stay on My day."""
    asyncio.run(_leads())
    assert [lead["contact"]["name"] for lead in _my_day(client)["hot_leads"]] == [
        "Omar Al Mazrouei"
    ]

    asyncio.run(_win_omars_lead())

    assert _my_day(client)["hot_leads"] == []


async def _win_omars_lead() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """update leads set stage_id = (select id from pipeline_stages
                                             where tenant_id = $1 and category = 'won' limit 1)
                where contact_id = (select id from contacts
                                     where tenant_id = $1 and full_name = 'Omar Al Mazrouei')""",
            TENANT_A,
        )
    finally:
        await conn.close()


def test_the_taking_chats_switch_reads_the_membership(client: TestClient) -> None:
    assert _my_day(client)["accepting_chats"] is True
    client.patch("/v1/me", json={"accepting_chats": False}, headers=_auth(SALES_1))
    assert _my_day(client)["accepting_chats"] is False


def test_a_manager_s_own_day_is_their_own(client: TestClient) -> None:
    """Their team's queue is the inbox; this screen is what they personally owe."""
    assert _my_day(client, MANAGER)["waiting_on_you"] == []


async def _wrote_twice() -> None:
    """Karim wrote half an hour before SALES_2 answered, and again a minute before."""
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        conversation = await _conversation(
            conn, "Karim Benali", owner=SALES_2, waiting_minutes=None
        )
        answered_at = NOW - timedelta(minutes=1)
        for minutes_before in (30, 1):
            await conn.execute(
                """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                         body, created_at)
                   values ($1, $2, 'in', 'customer', 'customer', 'Hello?', $3)""",
                TENANT_A,
                conversation,
                answered_at - timedelta(minutes=minutes_before),
            )
        await conn.execute(
            "update conversations set first_response_at = $2 where id = $1",
            conversation,
            answered_at,
        )
    finally:
        await conn.close()


def test_the_median_starts_at_the_customers_first_message(client: TestClient) -> None:
    """Somebody who wrote at 10:00 and again at 10:30 had waited half an hour
    when the 10:31 reply went out, not a minute."""
    asyncio.run(_wrote_twice())
    assert _my_day(client, SALES_2)["median_first_response_seconds"] == 30 * 60


async def test_a_wait_is_counted_in_the_hours_we_are_open(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """Fixed instants, so the test does not depend on the hour it runs at."""
    dubai = ZoneInfo("Asia/Dubai")
    hours = SalesSettings.model_validate(
        {"business_hours": {day: {"open": "09:00", "close": "21:00"} for day in WEEKDAYS}}
    )
    conversation = await su.fetchval("select id from conversations where tenant_id = $1", TENANT_A)
    await su.execute("delete from messages where conversation_id = $1", conversation)
    await su.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, body,
                                 created_at)
           values ($1, $2, 'in', 'customer', 'customer', 'Still there?', $3)""",
        TENANT_A,
        conversation,
        datetime(2026, 9, 21, 20, 59, tzinfo=dubai),
    )
    await su.execute(
        "update conversations set first_response_at = $2 where id = $1",
        conversation,
        datetime(2026, 9, 22, 9, 1, tzinfo=dubai),
    )
    since, until = numbers.day_window(date(2026, 9, 22), dubai)
    async with tenant_session(TENANT_A) as conn:
        waits = await numbers.answered(conn, since, until, tz=dubai, settings=hours)
    assert [wait.seconds for wait in waits] == [120]
