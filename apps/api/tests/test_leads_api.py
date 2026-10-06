"""Leads: where one starts, how it moves, and what it leaves behind."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
OMAR = "Omar Al Mazrouei"
KARIM = "Karim Benali"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


async def _seed_customers() -> dict[str, uuid.UUID]:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    ids: dict[str, uuid.UUID] = {}
    try:
        for name, owner in ((OMAR, SALES_1), (KARIM, SALES_2)):
            contact = await conn.fetchval(
                """insert into contacts (tenant_id, full_name, country, owner_id, team_id)
                   values ($1, $2, 'AE', $3, $4) returning id""",
                TENANT_A,
                name,
                owner,
                TEAM_LOCAL,
            )
            await conn.execute(
                """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
                   values ($1, $2, 'whatsapp_user_id', $3, true)""",
                TENANT_A,
                contact,
                f"AE.{name.split()[0].lower()}",
            )
            conversation = await conn.fetchval(
                """insert into conversations (tenant_id, contact_id, surface, owner_id, team_id,
                                              assigned_to, status)
                   values ($1, $2, 'whatsapp', $3, $4, $3, 'open') returning id""",
                TENANT_A,
                contact,
                owner,
                TEAM_LOCAL,
            )
            await conn.execute(
                """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                         body)
                   values ($1, $2, 'in', 'customer', 'customer', 'Is it available?')""",
                TENANT_A,
                conversation,
            )
            ids[name] = uuid.UUID(str(contact))
        return ids
    finally:
        await conn.close()


@pytest.fixture
def customers(_migrated: None) -> dict[str, uuid.UUID]:
    return asyncio.run(_seed_customers())


@pytest.fixture
def client(customers: dict[str, uuid.UUID]) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _create(client: TestClient, contact_id: uuid.UUID, user: uuid.UUID = SALES_1) -> dict[str, Any]:
    response = client.post("/v1/leads", json={"contact_id": str(contact_id)}, headers=_auth(user))
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _stages(client: TestClient, user: uuid.UUID = OWNER) -> list[dict[str, Any]]:
    board = client.get("/v1/pipelines", headers=_auth(user)).json()[0]
    return board["stages"]  # type: ignore[no-any-return]


def _stage(client: TestClient, name: str) -> str:
    return str(next(stage for stage in _stages(client) if stage["name"] == name)["id"])


def test_a_new_lead_starts_where_the_customer_already_is(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    lead = _create(client, customers[OMAR])
    assert lead["stage"]["name"] == "New"
    assert lead["stage"]["category"] == "open"
    assert lead["owner"]["name"] == "sales1", "the customer's owner owns their lead"
    assert lead["contact"]["name"] == OMAR
    assert lead["conversation_id"] is not None, "the drawer links back to the conversation"
    assert lead["source"] == "whatsapp"


def test_a_lead_for_a_customer_i_cannot_see_is_404(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    response = client.post(
        "/v1/leads", json={"contact_id": str(customers[KARIM])}, headers=_auth(SALES_1)
    )
    assert response.status_code == 404, response.text


def test_moving_a_lead_writes_its_history_and_a_line_in_the_conversation(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    lead = _create(client, customers[OMAR])
    qualified = _stage(client, "Qualified")

    response = client.patch(
        f"/v1/leads/{lead['id']}", json={"stage_id": qualified}, headers=_auth(SALES_1)
    )
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["stage"]["name"] == "Qualified"
    assert [entry["text"] for entry in moved["history"]] == ["New → Qualified"]
    assert moved["history"][0]["by"] == "sales1"

    thread = client.get(
        f"/v1/conversations/{lead['conversation_id']}/messages", headers=_auth(SALES_1)
    ).json()["data"]
    assert thread[-1]["event"]["text"] == "Lead moved to Qualified"
    assert thread[-1]["event"]["name"] == "Qualified"


def test_the_stage_clock_restarts_on_every_move(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    """Days in stage is what the board colours cards by."""
    lead = _create(client, customers[OMAR])
    first = lead["stage_entered_at"]
    moved = client.patch(
        f"/v1/leads/{lead['id']}",
        json={"stage_id": _stage(client, "Contacted")},
        headers=_auth(SALES_1),
    ).json()
    assert moved["stage_entered_at"] > first


def test_a_lost_lead_needs_a_reason(client: TestClient, customers: dict[str, uuid.UUID]) -> None:
    lead = _create(client, customers[OMAR])
    lost = _stage(client, "Lost")

    refused = client.patch(
        f"/v1/leads/{lead['id']}", json={"stage_id": lost}, headers=_auth(SALES_1)
    )
    assert refused.status_code == 422, refused.text

    accepted = client.patch(
        f"/v1/leads/{lead['id']}",
        json={"stage_id": lost, "lost_reason": "Bought from another dealer"},
        headers=_auth(SALES_1),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["lost_reason"] == "Bought from another dealer"


def test_winning_a_lead_clears_a_reason_it_never_had(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    lead = _create(client, customers[OMAR])
    client.patch(
        f"/v1/leads/{lead['id']}",
        json={"stage_id": _stage(client, "Lost"), "lost_reason": "Too expensive"},
        headers=_auth(SALES_1),
    )
    won = client.patch(
        f"/v1/leads/{lead['id']}", json={"stage_id": _stage(client, "Won")}, headers=_auth(SALES_1)
    )
    assert won.status_code == 200, won.text
    assert won.json()["lost_reason"] is None


def test_a_stage_from_another_pipeline_is_refused(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    lead = _create(client, customers[OMAR])
    other = asyncio.run(_a_second_board())
    response = client.patch(
        f"/v1/leads/{lead['id']}", json={"stage_id": str(other)}, headers=_auth(SALES_1)
    )
    assert response.status_code == 422, response.text


async def _a_second_board() -> uuid.UUID:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        pipeline = await conn.fetchval(
            "insert into pipelines (tenant_id, name) values ($1, 'Export') returning id", TENANT_A
        )
        return uuid.UUID(  # type: ignore[no-any-return]
            str(
                await conn.fetchval(
                    """insert into pipeline_stages (tenant_id, pipeline_id, name, position,
                                                    category)
                       values ($1, $2, 'Quoted', 0, 'open') returning id""",
                    TENANT_A,
                    pipeline,
                )
            )
        )
    finally:
        await conn.close()


def test_the_reasons_add_up_to_the_score_that_is_shown(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    lead = _create(client, customers[OMAR])
    asyncio.run(
        _score(
            uuid.UUID(lead["id"]),
            [
                {"signal": "asked_price", "evidence_message_id": None},
                {"signal": "requested_visit_or_test_drive", "evidence_message_id": None},
                {"signal": "silent", "times": 2},
            ],
        )
    )
    detail = client.get(f"/v1/leads/{lead['id']}", headers=_auth(SALES_1)).json()
    assert [reason["points"] for reason in detail["score_reasons"]] == [10, 15, -20]
    assert [reason["label"] for reason in detail["score_reasons"]][0] == "Asked the price"


async def _score(lead_id: uuid.UUID, signals: list[dict[str, Any]]) -> None:
    import json

    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            "update leads set score_signals = $2::jsonb where id = $1", lead_id, json.dumps(signals)
        )
    finally:
        await conn.close()


def test_a_salesperson_may_win_their_own_lead(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    """leads.mark_won_lost is a salesperson's permission: they close their own
    deals, and a manager who had to do it for them would be a bottleneck."""
    lead = _create(client, customers[OMAR])
    response = client.patch(
        f"/v1/leads/{lead['id']}", json={"stage_id": _stage(client, "Won")}, headers=_auth(SALES_1)
    )
    assert response.status_code == 200, response.text
    assert response.json()["stage"]["category"] == "won"


def test_the_board_comes_back_in_board_order(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    first = _create(client, customers[OMAR])
    second = _create(client, customers[KARIM], user=SALES_2)
    client.patch(
        f"/v1/leads/{second['id']}",
        json={"stage_id": _stage(client, "Negotiation")},
        headers=_auth(SALES_2),
    )

    board = client.get("/v1/leads", headers=_auth(OWNER)).json()
    # The workspace fixture has a lead of its own, so this asserts the order
    # between the two here: New before Negotiation, by the board's positions.
    mine = [lead for lead in board if lead["id"] in {first["id"], second["id"]}]
    assert [lead["id"] for lead in mine] == [first["id"], second["id"]]
    assert [lead["stage"]["name"] for lead in mine] == ["New", "Negotiation"]


def test_a_salesperson_sees_their_own_leads(
    client: TestClient, customers: dict[str, uuid.UUID]
) -> None:
    _create(client, customers[OMAR])
    _create(client, customers[KARIM], user=SALES_2)

    mine = client.get("/v1/leads", headers=_auth(SALES_1)).json()
    assert [lead["contact"]["name"] for lead in mine] == [OMAR]
    theirs = client.get("/v1/leads", headers=_auth(MANAGER)).json()
    assert {lead["contact"]["name"] for lead in theirs} >= {OMAR, KARIM}


def test_another_tenant_s_lead_is_404(client: TestClient) -> None:
    assert client.get(f"/v1/leads/{uuid.uuid4()}", headers=_auth(OWNER)).status_code == 404
