"""The customer list, the record, the timeline, and what a person may change."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

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
    TENANT_B,
    reseed_with_people,
)
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
NOW = datetime.now(UTC)

OMAR = "Omar Al Mazrouei"  # SALES_1, AE, vip, a hot lead and a voice note
KARIM = "Karim Benali"  # SALES_2, DZ, a warm lead
YOUSSEF = "Youssef El Idrissi"  # SALES_X, on the Export team
NOBODY = "Nadia Haddad"  # unassigned, in the Local team's pool


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


async def _customer(
    conn: asyncpg.Connection,
    name: str,
    *,
    owner: uuid.UUID | None,
    team: uuid.UUID,
    country: str = "AE",
    tags: list[str] | None = None,
    phone: str | None = None,
    seen_minutes_ago: int = 0,
    profile: dict[str, Any] | None = None,
) -> uuid.UUID:
    contact_id = await conn.fetchval(
        """insert into contacts (tenant_id, full_name, country, locale, owner_id, team_id,
                                 tags, last_seen_at, profile)
           values ($1, $2, $3, 'en', $4, $5, $6, $7, $8::jsonb) returning id""",
        TENANT_A,
        name,
        country,
        owner,
        team,
        tags or [],
        NOW - timedelta(minutes=seen_minutes_ago),
        json.dumps(profile or {}),
    )
    if phone:
        await conn.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'phone', $3, true)""",
            TENANT_A,
            contact_id,
            phone,
        )
    return uuid.UUID(str(contact_id))


async def _lead(
    conn: asyncpg.Connection,
    contact_id: uuid.UUID,
    *,
    owner: uuid.UUID | None,
    score: int,
    band: str,
    stage: str = "open",
) -> uuid.UUID:
    row = await conn.fetchrow(
        """select s.id as stage_id, s.pipeline_id from pipeline_stages s
            join pipelines p on p.id = s.pipeline_id
           where s.tenant_id = $1 and s.category = $2
           order by p.is_default desc, s.position limit 1""",
        TENANT_A,
        stage,
    )
    lead_id = await conn.fetchval(
        """insert into leads (tenant_id, contact_id, pipeline_id, stage_id, owner_id, score,
                              intent_band, budget_minor, currency)
           values ($1, $2, $3, $4, $5, $6, $7, 15000000, 'AED') returning id""",
        TENANT_A,
        contact_id,
        row["pipeline_id"],
        row["stage_id"],
        owner,
        score,
        band,
    )
    return uuid.UUID(str(lead_id))


async def _seed_customers() -> None:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        omar = await _customer(
            conn,
            OMAR,
            owner=SALES_1,
            team=TEAM_LOCAL,
            tags=["vip"],
            phone="+971500000101",
            seen_minutes_ago=1,
            profile={
                "budget": {
                    "value": {"amount_minor": 15000000, "currency": "AED"},
                    "source": "ai",
                    "evidence_message_id": None,
                    "updated_at": NOW.isoformat(),
                }
            },
        )
        lead = await _lead(conn, omar, owner=SALES_1, score=80, band="hot")
        conversation = await conn.fetchval(
            """insert into conversations (tenant_id, contact_id, surface, owner_id, team_id,
                                          assigned_to, status)
               values ($1, $2, 'whatsapp', $3, $4, $3, 'open') returning id""",
            TENANT_A,
            omar,
            SALES_1,
            TEAM_LOCAL,
        )
        for minutes, direction, body in (
            (30, "in", "Do you have the 2026 Hilux?"),
            (20, "out", "Yes, in white."),
        ):
            await conn.execute(
                """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                         body, created_at)
                   values ($1, $2, $3, case when $3 = 'in' then 'customer' else 'human' end,
                           case when $3 = 'in' then 'customer' else 'inbox' end, $4,
                           now() - make_interval(mins => $5))""",
                TENANT_A,
                conversation,
                direction,
                body,
                minutes,
            )
        await conn.execute(
            """insert into activities (tenant_id, lead_id, contact_id, kind, body, occurs_at)
               values ($1, $2, $3, 'stage_change', 'New → Qualified',
                       now() - make_interval(mins => 10))""",
            TENANT_A,
            lead,
            omar,
        )

        karim = await _customer(
            conn,
            KARIM,
            owner=SALES_2,
            team=TEAM_LOCAL,
            country="DZ",
            tags=["export"],
            phone="+213500000102",
            seen_minutes_ago=2,
        )
        await _lead(conn, karim, owner=SALES_2, score=50, band="warm")
        await _customer(
            conn, YOUSSEF, owner=SALES_X, team=TEAM_EXPORT, country="MA", seen_minutes_ago=3
        )
        await _customer(conn, NOBODY, owner=None, team=TEAM_LOCAL, seen_minutes_ago=4)
    finally:
        await conn.close()


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(_seed_customers())
    with TestClient(app) as test_client:
        yield test_client


def _list(client: TestClient, user: uuid.UUID, query: str = "") -> list[dict[str, Any]]:
    response = client.get(f"/v1/customers?{query}", headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()["data"]  # type: ignore[no-any-return]


def _names(rows: list[dict[str, Any]]) -> list[str]:
    return [row["name"] for row in rows]


def _id_of(client: TestClient, name: str) -> str:
    for row in _list(client, OWNER):
        if row["name"] == name:
            return str(row["id"])
    raise AssertionError(f"{name} is not in the seeded workspace")


def test_the_list_says_who_is_worth_calling(client: TestClient) -> None:
    rows = _list(client, OWNER)
    names = _names(rows)
    # Most recently seen first. The workspace fixture has customers of its own,
    # so this asserts the order between the four this file seeded.
    assert names.index(OMAR) < names.index(KARIM) < names.index(YOUSSEF) < names.index(NOBODY)
    omar = next(row for row in rows if row["name"] == OMAR)
    assert omar["phone"] == "+971500000101"
    assert omar["band"] == "hot", "the band comes from the best open lead"
    assert omar["owner"]["name"] == "sales1"
    assert omar["tags"] == ["vip"]
    assert omar["opted_out"] is False


def test_search_finds_a_customer_by_a_number_they_wrote_from(client: TestClient) -> None:
    assert _names(_list(client, OWNER, "q=500000101")) == [OMAR]
    assert _names(_list(client, OWNER, "q=benali")) == [KARIM]


def test_the_filters_narrow_it_the_way_the_url_says(client: TestClient) -> None:
    assert _names(_list(client, OWNER, "country=DZ")) == [KARIM]
    assert _names(_list(client, OWNER, "tag=vip")) == [OMAR]
    assert _names(_list(client, OWNER, f"owner_id={SALES_2}")) == [KARIM]
    assert _names(_list(client, OWNER, "band=hot")) == [OMAR]


def test_the_cursor_walks_the_list_without_skipping_a_shared_timestamp(
    client: TestClient,
) -> None:
    """Two customers seen in the same second must not hide each other."""
    asyncio.run(_same_second())
    seen: list[str] = []
    cursor = ""
    for _ in range(6):
        query = f"limit=2&cursor={cursor}" if cursor else "limit=2"
        response = client.get(f"/v1/customers?{query}", headers=_auth(OWNER))
        assert response.status_code == 200, response.text
        page = response.json()
        seen.extend(row["name"] for row in page["data"])
        cursor = page["next_cursor"] or ""
        if not cursor:
            break
    assert len(seen) == len(set(seen)), "a page repeated somebody"
    assert set(seen) >= {OMAR, KARIM, YOUSSEF, NOBODY}


async def _same_second() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "update contacts set last_seen_at = $2 where tenant_id = $1", TENANT_A, NOW
        )
    finally:
        await conn.close()


def test_a_salesperson_sees_their_own_customers_and_the_pool(client: TestClient) -> None:
    names = set(_names(_list(client, SALES_1)))
    assert OMAR in names
    assert NOBODY in names, "the unassigned pool is theirs to pick up"
    assert KARIM not in names, "a colleague's customer is not theirs to browse"


def test_a_manager_sees_their_teams_and_not_the_other_desk(client: TestClient) -> None:
    names = set(_names(_list(client, MANAGER)))
    assert {OMAR, KARIM} <= names
    assert YOUSSEF not in names, "the export desk is a different team"


def test_another_tenant_s_customer_is_404_not_403(client: TestClient) -> None:
    beta = asyncio.run(_a_beta_customer())
    response = client.get(f"/v1/customers/{beta}", headers=_auth(OWNER))
    assert response.status_code == 404, response.text
    assert response.json()["type"].endswith("not-found")


async def _a_beta_customer() -> uuid.UUID:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return uuid.UUID(  # type: ignore[no-any-return]
            str(await conn.fetchval("select id from contacts where tenant_id = $1", TENANT_B))
        )
    finally:
        await conn.close()


def test_the_record_carries_everything_the_panel_shows(client: TestClient) -> None:
    detail = client.get(f"/v1/customers/{_id_of(client, OMAR)}", headers=_auth(OWNER)).json()
    assert [identity["value"] for identity in detail["identities"]] == ["+971500000101"]
    assert detail["profile"]["budget"]["source"] == "ai"
    assert len(detail["leads"]) == 1
    lead = detail["leads"][0]
    assert lead["stage"]["category"] == "open"
    assert lead["budget"] == {"amount_minor": 15000000, "currency": "AED"}
    assert lead["score"] == 80


def test_the_timeline_merges_what_was_said_and_what_was_done(client: TestClient) -> None:
    response = client.get(f"/v1/customers/{_id_of(client, OMAR)}/timeline", headers=_auth(OWNER))
    assert response.status_code == 200, response.text
    entries = response.json()["data"]
    assert [entry["kind"] for entry in entries] == ["activity", "message", "message"], (
        "newest first, both kinds in one list"
    )
    assert entries[0]["data"]["body"] == "New → Qualified"


def test_a_timeline_i_am_not_allowed_to_read_is_404(client: TestClient) -> None:
    other = _id_of(client, KARIM)
    assert client.get(f"/v1/customers/{other}/timeline", headers=_auth(SALES_1)).status_code == 404


def test_editing_the_budget_makes_it_a_person_s(client: TestClient) -> None:
    customer_id = _id_of(client, OMAR)
    response = client.patch(
        f"/v1/customers/{customer_id}",
        json={"profile": {"budget": {"amount_minor": 14000000, "currency": "AED"}}},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 200, response.text
    budget = response.json()["profile"]["budget"]
    assert budget["source"] == "human"
    assert budget["value"]["amount_minor"] == 14000000
    assert response.json()["profile_updated_at"] is not None


def test_a_field_we_do_not_record_is_refused(client: TestClient) -> None:
    response = client.patch(
        f"/v1/customers/{_id_of(client, OMAR)}",
        json={"profile": {"shoe_size": 44}},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 422
    assert "shoe_size" in response.json()["detail"]


def test_tags_are_tidied_rather_than_stored_as_typed(client: TestClient) -> None:
    response = client.patch(
        f"/v1/customers/{_id_of(client, OMAR)}",
        json={"tags": [" vip ", "vip", "", "export"]},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 200, response.text
    assert response.json()["tags"] == ["vip", "export"]


def test_editing_a_customer_i_cannot_see_is_404(client: TestClient) -> None:
    response = client.patch(
        f"/v1/customers/{_id_of(client, KARIM)}",
        json={"name": "Mine now"},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 404, response.text
