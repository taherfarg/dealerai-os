"""The manager's dashboard: every number is the rows behind it, seen as the caller may see them."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import (
    MANAGER,
    OWNER,
    SALES_1,
    SALES_2,
    SALES_X,
    TEAM_EXPORT,
    TEAM_LOCAL,
    TENANT_A,
    reseed_with_people,
)
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.sales.dashboard import rank

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
VIEWER = uuid.UUID("cccccccc-1111-4000-8000-000000000009")
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


async def _customer(
    conn: asyncpg.Connection,
    name: str,
    *,
    owner: uuid.UUID,
    team: uuid.UUID,
    waiting_minutes: int | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A customer who wrote today, and their conversation — waiting past a
    five-minute target when `waiting_minutes` is given."""
    contact = await conn.fetchval(
        """insert into contacts (tenant_id, full_name, owner_id, team_id)
           values ($1, $2, $3, $4) returning id""",
        TENANT_A,
        name,
        owner,
        team,
    )
    waiting_since = NOW - timedelta(minutes=waiting_minutes) if waiting_minutes else None
    conversation = await conn.fetchval(
        """insert into conversations (tenant_id, contact_id, surface, status, owner_id, team_id,
                                      assigned_to, waiting_since, sla_due_at, last_message_at)
           values ($1, $2, 'whatsapp', 'open', $3, $4, $3, $5::timestamptz,
                   $5::timestamptz + interval '5 minutes', now())
           returning id""",
        TENANT_A,
        contact,
        owner,
        team,
        waiting_since,
    )
    return contact, conversation


async def _morning() -> dict[str, uuid.UUID]:
    """Today, in Dubai: three new conversations (two Local, one Export); SALES_1
    answered one after four minutes; SALES_2 missed a target and that customer
    is still waiting past it, as is the Export one; a Local lead won today and
    an Export one lost; a hot Local lead with no task; two of SALES_2's tasks
    overdue; one reply typed on the phone.

    Starts from reseed_with_people() and deletes tenant A's fixture customer
    first, so every row the tiles count is one this test wrote."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("delete from conversations where tenant_id = $1", TENANT_A)
        await conn.execute("delete from contacts where tenant_id = $1", TENANT_A)

        omar, answered = await _customer(conn, "Omar Answered", owner=SALES_1, team=TEAM_LOCAL)
        karim, waiting = await _customer(
            conn, "Karim Waiting", owner=SALES_2, team=TEAM_LOCAL, waiting_minutes=20
        )
        salma, export = await _customer(
            conn, "Salma Export", owner=SALES_X, team=TEAM_EXPORT, waiting_minutes=15
        )

        asked_at = NOW - timedelta(minutes=5)
        await conn.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, body,
                                     created_at)
               values ($1, $2, 'in', 'customer', 'customer', 'Is it there?', $3)""",
            TENANT_A,
            answered,
            asked_at,
        )
        for origin in ("inbox", "phone_app"):
            await conn.execute(
                """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                         author_user_id, body, created_at)
                   values ($1, $2, 'out', 'human', $3, $4, 'Yes.', $5)""",
                TENANT_A,
                answered,
                origin,
                SALES_1,
                asked_at + timedelta(minutes=4),
            )
        await conn.execute(
            "update conversations set first_response_at = $2 where id = $1",
            answered,
            asked_at + timedelta(minutes=4),
        )
        await conn.execute(
            """insert into sla_misses (tenant_id, conversation_id, assigned_to, waiting_since,
                                       due_at)
               values ($1, $2, $3, $4, $5)""",
            TENANT_A,
            waiting,
            SALES_2,
            NOW - timedelta(minutes=20),
            NOW - timedelta(minutes=15),
        )

        stages = {
            row["category"]: row
            for row in await conn.fetch(
                """select distinct on (category) category, id, pipeline_id from pipeline_stages
                    where tenant_id = $1 order by category, position""",
                TENANT_A,
            )
        }
        for contact, owner, team, category, band in (
            (omar, SALES_1, TEAM_LOCAL, "won", "warm"),
            (salma, SALES_X, TEAM_EXPORT, "lost", "cold"),
            (karim, SALES_2, TEAM_LOCAL, "open", "hot"),
        ):
            await conn.execute(
                """insert into leads (tenant_id, contact_id, pipeline_id, stage_id, owner_id,
                                      team_id, intent_band, score, stage_entered_at)
                   values ($1, $2, $3, $4, $5, $6, $7, 50, now())""",
                TENANT_A,
                contact,
                stages[category]["pipeline_id"],
                stages[category]["id"],
                owner,
                team,
                band,
            )
        for title in ("Call Karim back", "Send Karim the brochure"):
            await conn.execute(
                """insert into tasks (tenant_id, title, due_at, assignee_id)
                   values ($1, $2, now() - interval '1 hour', $3)""",
                TENANT_A,
                title,
                SALES_2,
            )

        await conn.execute(
            """insert into auth.users (id, email) values ($1, 'viewer@example.test')
               on conflict do nothing""",
            VIEWER,
        )
        await conn.execute(
            "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'viewer')",
            TENANT_A,
            VIEWER,
        )
        return {"waiting": waiting, "export": export, "open_stage": stages["open"]["id"]}
    finally:
        await conn.close()


@pytest.fixture
def morning(_migrated: None) -> dict[str, uuid.UUID]:
    return asyncio.run(_morning())


@pytest.fixture
def client(morning: dict[str, uuid.UUID]) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _board(client: TestClient, user: uuid.UUID = OWNER, **query: str) -> dict[str, Any]:
    response = client.get("/v1/dashboard/manager", params=query, headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_the_tiles_are_the_rows_behind_them(client: TestClient) -> None:
    tiles = _board(client)["tiles"]
    assert tiles == {
        "new_conversations": 3,
        "waiting_now": 2,
        "median_first_response_seconds": 240,
        "first_response_target_seconds": 300,
        "missed_targets": 1,
        "new_leads": 3,
        "hot_leads": 1,
        "won": 1,
        "lost": 1,
    }


def test_a_manager_counts_her_teams_and_nobody_elses(client: TestClient) -> None:
    board = _board(client, MANAGER)
    assert board["tiles"]["new_conversations"] == 2
    assert board["tiles"]["waiting_now"] == 1
    assert board["tiles"]["lost"] == 0, "the lost lead is Export's"
    assert [row["user"]["name"] for row in board["team"]] == ["manager", "sales1", "sales2"]
    owner_view = [row["user"]["name"] for row in _board(client)["team"]]
    assert owner_view == ["manager", "sales1", "sales2", "salesx"]


def test_a_miss_counts_against_whoever_had_the_customer(client: TestClient) -> None:
    team = {row["user"]["name"]: row for row in _board(client)["team"]}
    assert team["sales2"]["missed_targets"] == 1
    assert team["sales1"]["missed_targets"] == 0
    assert team["sales1"]["median_first_response_seconds"] == 240
    assert team["sales2"]["overdue_tasks"] == 2
    assert (team["sales2"]["hot"], team["sales1"]["won_this_month"]) == (1, 1)


def test_waiting_is_the_longest_wait_first(
    client: TestClient, morning: dict[str, uuid.UUID]
) -> None:
    waiting = _board(client)["waiting"]
    assert [row["id"] for row in waiting] == [str(morning["waiting"]), str(morning["export"])]


def test_the_pipeline_counts_open_leads_per_stage(
    client: TestClient, morning: dict[str, uuid.UUID]
) -> None:
    counted = {row["stage_id"]: row["leads"] for row in _board(client)["pipeline"] if row["leads"]}
    assert counted == {str(morning["open_stage"]): 1}


def test_phone_replies_are_counted_apart_from_the_inbox(client: TestClient) -> None:
    share = _board(client)["phone_share"]
    assert share == {"this_week": {"inbox": 1, "phone": 1}, "last_week": {"inbox": 0, "phone": 0}}


def test_a_date_counts_that_day(client: TestClient) -> None:
    yesterday = (NOW.astimezone(ZoneInfo("Asia/Dubai")) - timedelta(days=1)).date()
    board = _board(client, date=yesterday.isoformat())
    assert board["date"] == yesterday.isoformat()
    assert board["tiles"]["new_conversations"] == 0
    assert board["tiles"]["waiting_now"] == 2, "waiting is always now"


def test_a_salesperson_is_refused_and_a_viewer_is_not(client: TestClient) -> None:
    response = client.get("/v1/dashboard/manager", headers=_auth(SALES_1))
    assert response.status_code == 403
    assert _board(client, VIEWER)["tiles"] == _board(client)["tiles"]


def test_the_brief_lists_what_needs_doing_now(
    client: TestClient, morning: dict[str, uuid.UUID]
) -> None:
    brief = _board(client)["brief"]
    assert brief["headline"] is None, "nothing has written today's brief yet"
    assert [(item["kind"], item["name"]) for item in brief["items"]] == [
        ("waiting", "Karim Waiting"),
        ("waiting", "Salma Export"),
        ("hot_lead", "Karim Waiting"),
        ("overdue_tasks", "sales2"),
    ]
    assert brief["items"][0]["owner"]["name"] == "sales2"
    assert brief["items"][3]["count"] == 2


def test_the_brief_puts_two_of_each_kind_of_trouble_first() -> None:
    waits = [{"kind": "waiting", "id": n} for n in range(4)]
    hot = [{"kind": "hot_lead", "id": n} for n in range(3)]
    overdue = [{"kind": "overdue_tasks", "id": 0}]
    assert [(item["kind"], item["id"]) for item in rank(waits, hot, overdue)] == [
        ("waiting", 0),
        ("waiting", 1),
        ("hot_lead", 0),
        ("hot_lead", 1),
        ("overdue_tasks", 0),
    ]
