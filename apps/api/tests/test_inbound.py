"""Lifecycle L4: where a bought car is, what is missing, and what it cost to bring in.

The exit criterion runs through all of it: a US-auction car shows where it is
and what is missing, and its landed cost is complete the day it arrives. The
reading rule is pure and first — a shipping document is this car's only when
this car's VIN is on it — then the journey as the API and the worker run it,
and the wall: where a car is, is everybody's; its papers are not.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from PIL import Image

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, USER_A, reseed_with_people
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.db import session
from dealerai.events.bus import Event
from dealerai.events.handlers.lifecycle import on_inbound_arrived, on_inbound_sweep
from dealerai.lifecycle import inbound
from dealerai.lifecycle.inbound import SeenVin, ShippingReading, expected_costs, verify
from dealerai.main import app

VIN = "1C4RJFBG5MC000123"
OTHER = "5YJ3E1EA7KF000456"
TODAY = date(2026, 11, 4)

# --------------------------------------------------------------------------
# the rules — pure
# --------------------------------------------------------------------------


def test_an_auction_import_always_has_five_kinds_of_cost() -> None:
    assert expected_costs("import", "auction") == [
        "purchase",
        "auction_fee",
        "transport",
        "shipping",
        "customs",
    ]
    assert expected_costs("local", "private") == ["purchase"]


def _bl(**over: Any) -> ShippingReading:
    base: dict[str, Any] = {
        "kind": "bill_of_lading",
        "reference": "MEDU8812345",
        "reference_quote": "B/L No. MEDU8812345",
        "carrier": "MSC",
        "vessel": "MSC AURORA",
        "container": "MSCU1234567",
        "port_of_loading": "Houston, TX",
        "port_of_discharge": "Jebel Ali",
        "departed_on": "2026-10-20",
        "eta": "2026-11-18",
        "vins": [SeenVin(vin=VIN, quote=f"2021 JEEP GRAND CHEROKEE VIN {VIN}")],
    }
    return ShippingReading(**{**base, **over})


def test_a_bill_of_lading_for_this_car_proves_it_sailed() -> None:
    proposal = verify(_bl(), car_vin=VIN, today=TODAY)
    assert proposal.matches
    assert proposal.milestone == "departed"
    assert proposal.paper == "bill_of_lading"
    assert proposal.departed_on == date(2026, 10, 20)
    assert proposal.eta == date(2026, 11, 18)
    assert proposal.warnings == []


def test_a_container_of_cars_matches_the_one_on_it() -> None:
    proposal = verify(
        _bl(
            vins=[
                SeenVin(vin=OTHER, quote=f"1. TESLA MODEL 3 {OTHER}"),
                SeenVin(vin=VIN.lower(), quote=f"2. JEEP {VIN[:8]} {VIN[8:]}"),
            ]
        ),
        car_vin=VIN,
        today=TODAY,
    )
    assert proposal.matches, "spacing and case are how VINs are printed, not a different car"
    assert proposal.vins == [OTHER, VIN]


def test_another_cars_bill_of_lading_does_not_match() -> None:
    proposal = verify(_bl(vins=[SeenVin(vin=OTHER, quote=OTHER)]), car_vin=VIN, today=TODAY)
    assert not proposal.matches
    assert proposal.warnings == [f"this car's VIN {VIN} is not on the document (it names {OTHER})"]


def test_a_vin_that_is_not_a_vin_or_not_where_it_was_read_is_dropped() -> None:
    proposal = verify(
        _bl(
            vins=[
                SeenVin(vin="1C4RJFBG5MC00O123", quote="1C4RJFBG5MC00O123"),  # a letter O
                SeenVin(vin=VIN, quote="VIN illegible"),
            ]
        ),
        car_vin=VIN,
        today=TODAY,
    )
    assert proposal.vins == []
    assert not proposal.matches


def test_a_car_with_no_vin_cannot_be_matched() -> None:
    proposal = verify(_bl(), car_vin=None, today=TODAY)
    assert not proposal.matches
    assert "no VIN recorded" in proposal.warnings[0]


def test_a_sailing_in_the_future_is_a_schedule_not_a_departure() -> None:
    proposal = verify(_bl(departed_on="2026-11-20"), car_vin=VIN, today=TODAY)
    assert proposal.milestone is None
    assert proposal.departed_on is None
    assert proposal.warnings == ["the departure date 2026-11-20 has not happened yet"]


def test_a_reference_not_where_it_was_read_is_not_kept() -> None:
    proposal = verify(_bl(reference_quote="Booking 99"), car_vin=VIN, today=TODAY)
    assert proposal.reference is None


def test_a_customs_declaration_proves_clearance() -> None:
    proposal = verify(_bl(kind="customs_declaration", departed_on=None), car_vin=VIN, today=TODAY)
    assert (proposal.milestone, proposal.paper) == ("customs_cleared", "customs_declaration")


# --------------------------------------------------------------------------
# the wall — Postgres, as the application role
# --------------------------------------------------------------------------


async def _car(su: asyncpg.Connection, *, vin: str | None = VIN) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, model_year, vin, price_minor, status)
           values ($1, $2, 'Jeep', 'Grand Cherokee', 2021, $3, 14500000, 'draft')""",
        vehicle_id,
        TENANT_A,
        vin,
    )
    await su.execute(
        """insert into vehicle_acquisitions (vehicle_id, tenant_id, source, purchased_at)
           values ($1, $2, 'auction', '2026-10-01')""",
        vehicle_id,
        TENANT_A,
    )
    return vehicle_id


async def _cost(
    su: asyncpg.Connection, vehicle_id: uuid.UUID, category: str, status: str = "actual"
) -> None:
    await su.execute(
        """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                      fx_rate, amount_tenant_minor, incurred_at, status)
           values ($1, $2, $3, 100000, 'AED', 1, 100000, current_date, $4)""",
        TENANT_A,
        vehicle_id,
        category,
        status,
    )


async def test_where_a_car_is_is_everyones_and_its_papers_are_not(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.start(conn, TENANT_A, vehicle_id, "import")
    async with session.tenant_session(TENANT_A, user_id=USER_A) as conn:
        assert await conn.fetchval("select count(*) from inbound_milestones") == 9
        assert await conn.fetchval("select count(*) from inbound_documents") == 0
    async with session.tenant_session(TENANT_A, user_id=USER_A, buy_side=True) as conn:
        assert await conn.fetchval("select count(*) from inbound_documents") == 5


async def test_starting_a_journey_knows_the_car_was_bought(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.start(conn, TENANT_A, vehicle_id, "import")
    row = await su.fetchrow(
        """select status, done_on from inbound_milestones
            where vehicle_id = $1 and code = 'purchased'""",
        vehicle_id,
    )
    assert (row["status"], row["done_on"]) == ("done", date(2026, 10, 1))


async def test_changing_the_route_keeps_what_both_routes_share(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.start(conn, TENANT_A, vehicle_id, "import")
        await inbound.mark(conn, TENANT_A, vehicle_id, "paid", status="done")
        await inbound.start(conn, TENANT_A, vehicle_id, "local")
    rows = await su.fetch(
        "select code, status from inbound_milestones where vehicle_id = $1 order by position",
        vehicle_id,
    )
    assert [(r["code"], r["status"]) for r in rows] == [
        ("purchased", "done"),
        ("paid", "done"),
        ("collected", "pending"),
        ("registered", "pending"),
    ]


async def test_the_landed_cost_is_complete_only_with_every_fee_actual(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.start(conn, TENANT_A, vehicle_id, "import")
    await _cost(su, vehicle_id, "purchase")
    await _cost(su, vehicle_id, "auction_fee")
    await _cost(su, vehicle_id, "shipping", status="estimate")
    async with session.tenant_session(TENANT_A) as conn:
        found = await inbound.missing(conn, vehicle_id)
    assert found is not None
    assert found.costs == ["transport", "customs"]
    assert found.estimated == ["shipping"], "an estimate is not what it cost"
    assert len(found.documents) == 5

    for category in ("transport", "shipping", "customs"):
        await _cost(su, vehicle_id, category)
    await su.execute(
        "update inbound_documents set status = 'received' where vehicle_id = $1", vehicle_id
    )
    async with session.tenant_session(TENANT_A) as conn:
        found = await inbound.missing(conn, vehicle_id)
    assert found is not None and found.nothing


# --------------------------------------------------------------------------
# the worker
# --------------------------------------------------------------------------


def _event(event_type: str, payload: dict[str, Any]) -> Event:
    return Event(
        id=0,
        tenant_id=TENANT_A,
        event_type=event_type,
        payload=payload,
        attempts=1,
        dedupe_key=None,
    )


async def test_arriving_is_recorded_and_announced_once(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.start(conn, TENANT_A, vehicle_id, "import")
        await inbound.mark(conn, TENANT_A, vehicle_id, "delivered", status="done")
        await inbound.mark(conn, TENANT_A, vehicle_id, "delivered", status="done")
    assert await su.fetchval(
        "select arrived_at is not null from vehicle_inbound where vehicle_id = $1", vehicle_id
    )
    assert (
        await su.fetchval("select count(*) from events where event_type = 'inbound.arrived'") == 1
    )
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.mark(conn, TENANT_A, vehicle_id, "delivered", status="pending")
    assert await su.fetchval(
        "select arrived_at is null from vehicle_inbound where vehicle_id = $1", vehicle_id
    ), "undone by mistake is not arrived"


async def test_the_arrival_notice_says_what_is_still_missing(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.start(conn, TENANT_A, vehicle_id, "import")
    for category in ("purchase", "auction_fee", "transport", "shipping"):
        await _cost(su, vehicle_id, category)
    await _cost(su, vehicle_id, "customs", status="estimate")
    await su.execute(
        """update inbound_documents set status = 'received'
            where vehicle_id = $1 and code <> 'customs_certificate'""",
        vehicle_id,
    )
    await on_inbound_arrived(_event("inbound.arrived", {"vehicle_id": str(vehicle_id)}))
    note = await su.fetchrow(
        "select user_id, title, body, href from notifications where kind = 'inbound_arrived'"
    )
    assert note["user_id"] == USER_A
    assert note["title"] == "2021 Jeep Grand Cherokee arrived"
    assert note["body"] == (
        "Still missing — papers: customs certificate; still estimates: customs."
    )
    assert note["href"] == f"/inventory/{vehicle_id}"


async def test_a_complete_arrival_says_so(db: None, seeded: None, su: asyncpg.Connection) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        await inbound.start(conn, TENANT_A, vehicle_id, "local")
    for category in ("purchase", "auction_fee"):
        await _cost(su, vehicle_id, category)
    await su.execute(
        "update inbound_documents set status = 'not_needed' where vehicle_id = $1", vehicle_id
    )
    await on_inbound_arrived(_event("inbound.arrived", {"vehicle_id": str(vehicle_id)}))
    body = await su.fetchval("select body from notifications where kind = 'inbound_arrived'")
    assert body == "Its papers are in and its landed cost is complete."


async def test_cars_past_their_eta_are_named_once_a_morning(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    late, on_time, arrived = [await _car(su, vin=None) for _ in range(3)]
    async with session.tenant_session(TENANT_A) as conn:
        for vehicle_id in (late, on_time, arrived):
            await inbound.start(conn, TENANT_A, vehicle_id, "import")
        await inbound.mark(conn, TENANT_A, arrived, "delivered", status="done")
    yesterday = date.today() - timedelta(days=2)
    await su.execute(
        "update vehicle_inbound set eta = $2 where vehicle_id = any($1::uuid[])",
        [late, arrived],
        yesterday,
    )
    await su.execute(
        "update vehicle_inbound set eta = $2 where vehicle_id = $1",
        on_time,
        date.today() + timedelta(days=9),
    )
    for _ in range(2):
        await on_inbound_sweep(_event("inbound.sweep_due", {"date": "2026-11-04"}))
    rows = await su.fetch("select title, href from notifications where kind = 'inbound_late'")
    assert [(r["title"], r["href"]) for r in rows] == [("A car is past its ETA", "/inventory")]


# --------------------------------------------------------------------------
# the door — the API, per role
# --------------------------------------------------------------------------

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


async def _people_and_a_car() -> uuid.UUID:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await _car(conn)
    finally:
        await conn.close()


@pytest.fixture
def car(_migrated: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return asyncio.run(_people_and_a_car())


@pytest.fixture
def client(car: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _start(client: TestClient, car: uuid.UUID, **fields: Any) -> dict[str, Any]:
    response = client.patch(
        f"/v1/vehicles/{car}/inbound", json={"route": "import", **fields}, headers=auth(MANAGER)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_salesperson_sees_where_the_car_is_and_not_its_papers(
    client: TestClient, car: uuid.UUID
) -> None:
    _start(client, car, eta="2026-12-01", carrier="MSC")
    seen = client.get(f"/v1/vehicles/{car}/inbound", headers=auth(SALES_1)).json()
    assert seen["started"] and seen["eta"] == "2026-12-01" and seen["carrier"] == "MSC"
    assert seen["stage"] == "paid", "purchased is done; paying is next"
    assert seen["documents"] is None and seen["missing"] is None

    owner = client.get(f"/v1/vehicles/{car}/inbound", headers=auth(OWNER)).json()
    assert [d["code"] for d in owner["documents"]] == list(inbound.DOCUMENTS["import"])
    assert owner["missing"]["costs"] == [
        "purchase",
        "auction_fee",
        "transport",
        "shipping",
        "customs",
    ]
    assert owner["missing"]["complete"] is False


def test_where_a_car_is_is_the_step_after_the_furthest_reached(
    client: TestClient, car: uuid.UUID
) -> None:
    _start(client, car)
    journey = client.post(
        f"/v1/vehicles/{car}/inbound/milestones/departed",
        json={"status": "done", "done_on": "2026-10-14"},
        headers=auth(MANAGER),
    ).json()
    assert journey["stage"] == "arrived_port", "a car at sea has been paid for"


def test_a_salesperson_cannot_move_the_journey(client: TestClient, car: uuid.UUID) -> None:
    response = client.patch(
        f"/v1/vehicles/{car}/inbound", json={"route": "import"}, headers=auth(SALES_1)
    )
    assert response.status_code == 403


def test_a_journey_starts_with_its_route(client: TestClient, car: uuid.UUID) -> None:
    response = client.patch(
        f"/v1/vehicles/{car}/inbound", json={"carrier": "MSC"}, headers=auth(MANAGER)
    )
    assert response.status_code == 422


def test_a_car_past_its_eta_is_late_until_it_arrives(client: TestClient, car: uuid.UUID) -> None:
    assert _start(client, car, eta="2026-01-01")["late"] is True
    arrived = client.post(
        f"/v1/vehicles/{car}/inbound/milestones/delivered",
        json={"status": "done", "done_on": "2026-01-03"},
        headers=auth(MANAGER),
    ).json()
    assert arrived["late"] is False
    assert arrived["stage"] is None
    assert arrived["arrived_at"] is not None


def test_a_step_the_route_does_not_have_is_not_there(client: TestClient, car: uuid.UUID) -> None:
    _start(client, car, route="local")
    response = client.post(
        f"/v1/vehicles/{car}/inbound/milestones/departed",
        json={"status": "done"},
        headers=auth(MANAGER),
    )
    assert response.status_code == 404


def test_a_paper_uploaded_is_received(client: TestClient, car: uuid.UUID) -> None:
    _start(client, car)
    response = client.post(
        f"/v1/vehicles/{car}/inbound/documents/title/file",
        files={"file": ("title.jpg", _jpeg(), "image/jpeg")},
        headers=auth(MANAGER),
    )
    assert response.status_code == 200, response.text
    [title] = [d for d in response.json()["documents"] if d["code"] == "title"]
    assert title["status"] == "received"
    assert title["document_path"].startswith(f"{TENANT_A}/inbound/")


def test_a_paper_not_needed_leaves_the_checklist(client: TestClient, car: uuid.UUID) -> None:
    _start(client, car)
    after = client.patch(
        f"/v1/vehicles/{car}/inbound/documents/customs_certificate",
        json={"status": "not_needed"},
        headers=auth(MANAGER),
    ).json()
    assert "customs_certificate" not in after["missing"]["documents"]


def test_a_confirmed_paper_must_be_this_dealerships(client: TestClient, car: uuid.UUID) -> None:
    _start(client, car)
    response = client.post(
        f"/v1/vehicles/{car}/inbound/confirm",
        json={"paper": {"code": "title", "document_path": f"{uuid.uuid4()}/inbound/x.pdf"}},
        headers=auth(MANAGER),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# reading a shipping document
# --------------------------------------------------------------------------

READING: dict[str, Any] = {
    "kind": "bill_of_lading",
    "reference": "MEDU8812345",
    "reference_quote": "B/L No. MEDU8812345",
    "carrier": "MSC",
    "vessel": "MSC AURORA",
    "container": "MSCU1234567",
    "port_of_loading": "Houston, TX",
    "port_of_discharge": "Jebel Ali",
    "departed_on": "2026-10-20",
    "eta": "2026-11-18",
    "vins": [{"vin": VIN, "quote": f"2021 JEEP GRAND CHEROKEE VIN {VIN}"}],
}


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    class Models:
        async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
            calls.append(kwargs)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model", parts=[types.Part(text=json.dumps(READING))]
                        ),
                        finish_reason=types.FinishReason.STOP,
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=1200, candidates_token_count=200, total_token_count=1400
                ),
            )

    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": Models()})()})()
    )
    return calls


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


def _read(client: TestClient, car: uuid.UUID) -> dict[str, Any]:
    response = client.post(
        f"/v1/vehicles/{car}/inbound/read",
        files={"file": ("bl.jpg", _jpeg(), "image/jpeg")},
        headers=auth(MANAGER),
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_reading_a_bill_of_lading_proposes_and_applies_nothing(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    _start(client, car)
    proposal = _read(client, car)
    assert proposal["matches"] is True
    assert (proposal["milestone"], proposal["paper"]) == ("departed", "bill_of_lading")
    assert proposal["document_path"].startswith(f"{TENANT_A}/inbound/")

    journey = client.get(f"/v1/vehicles/{car}/inbound", headers=auth(OWNER)).json()
    assert journey["reference"] is None
    assert all(m["status"] != "done" or m["code"] == "purchased" for m in journey["milestones"])


def test_the_model_is_not_told_the_vin(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    """Told the VIN, a model can find it. Not told, it can only read it."""
    _start(client, car)
    _read(client, car)
    assert VIN not in str(model[0]["contents"])
    assert VIN not in str(model[0]["config"])


def test_another_cars_document_does_not_match(
    client: TestClient, car: uuid.UUID, model: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(READING, "vins", [{"vin": OTHER, "quote": OTHER}])
    _start(client, car)
    proposal = _read(client, car)
    assert proposal["matches"] is False
    assert proposal["warnings"][0].startswith(f"this car's VIN {VIN} is not on the document")


def test_confirming_a_reading_applies_it_in_one_go(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    _start(client, car)
    proposal = _read(client, car)
    response = client.post(
        f"/v1/vehicles/{car}/inbound/confirm",
        json={
            "journey": {
                "carrier": proposal["carrier"],
                "reference": proposal["reference"],
                "vessel": proposal["vessel"],
                "container": proposal["container"],
                "port_of_loading": proposal["port_of_loading"],
                "port_of_discharge": proposal["port_of_discharge"],
                "eta": proposal["eta"],
            },
            "milestone": {"code": proposal["milestone"], "done_on": proposal["departed_on"]},
            "paper": {"code": proposal["paper"], "document_path": proposal["document_path"]},
        },
        headers=auth(MANAGER),
    )
    assert response.status_code == 200, response.text
    journey = response.json()
    assert (journey["reference"], journey["eta"]) == ("MEDU8812345", "2026-11-18")
    [departed] = [m for m in journey["milestones"] if m["code"] == "departed"]
    assert (departed["status"], departed["done_on"]) == ("done", "2026-10-20")
    [bl] = [d for d in journey["documents"] if d["code"] == "bill_of_lading"]
    assert bl["status"] == "received" and bl["document_path"] == proposal["document_path"]
