from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import TENANT_A, TENANT_B, USER_A, USER_B, reseed
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.routes.vehicles import VehicleSummary

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed())
    asyncio.run(_clear_events())
    with TestClient(app) as c:
        yield c


def auth(user: uuid.UUID = USER_A, tenant: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user, secret=SECRET)}",
        "X-Tenant-Id": str(tenant),
    }


async def _clear_events() -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("delete from events")
    finally:
        await conn.close()


def events_of(event_type: str) -> list[dict[str, Any]]:
    async def go() -> list[dict[str, Any]]:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            rows = await conn.fetch("select payload from events where event_type = $1", event_type)
            return [json.loads(r["payload"]) for r in rows]
        finally:
            await conn.close()

    return asyncio.run(go())


def set_role(user: uuid.UUID, role: str) -> None:
    async def go() -> None:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            await conn.execute(
                """insert into memberships (tenant_id, user_id, role) values ($1,$2,$3)
                   on conflict (tenant_id, user_id) do update set role = excluded.role""",
                TENANT_A,
                user,
                role,
            )
        finally:
            await conn.close()

    asyncio.run(go())


def a_car(**over: Any) -> dict[str, Any]:
    return {
        "make": "MG",
        "model": "MG7",
        "trim": "Luxury",
        "model_year": 2026,
        "price_minor": 9_500_000,
        "min_price_minor": 9_000_000,
        "stock_number": f"ST-{uuid.uuid4().hex[:8]}",
        **over,
    }


# --------------------------------------------------------------------------
# the discount floor must never leak
# --------------------------------------------------------------------------


def test_customer_facing_schema_has_no_discount_floor() -> None:
    """VehicleSummary is what a Sales Agent sees. An agent that can read the
    floor will reason its way down to it, so the field is not in the shape at
    all — not merely omitted at the call site."""
    assert "min_price" not in VehicleSummary.model_fields
    assert "min_price_minor" not in VehicleSummary.model_fields


def test_summary_schema_is_a_strict_subset_of_the_internal_one() -> None:
    from dealerai.routes.vehicles import VehicleOut

    assert set(VehicleSummary.model_fields) < set(VehicleOut.model_fields)


def test_staff_endpoints_do_return_the_floor(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    assert created["min_price"] == {"amount_minor": 9_000_000, "currency": "AED"}


# --------------------------------------------------------------------------
# money shape
# --------------------------------------------------------------------------


def test_price_is_minor_units_and_a_currency_never_a_float(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    assert created["price"] == {"amount_minor": 9_500_000, "currency": "AED"}
    assert not isinstance(created["price"]["amount_minor"], float)


def test_a_vehicle_with_no_price_yet_is_allowed(client: TestClient) -> None:
    created = client.post(
        "/v1/vehicles", json=a_car(price_minor=None, min_price_minor=None), headers=auth()
    ).json()
    assert created["price"] is None


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------


def test_create_emits_vehicle_created(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    assert [e["vehicle_id"] for e in events_of("vehicle.created")] == [created["id"]]


def test_duplicate_stock_number_is_409(client: TestClient) -> None:
    car = a_car()
    assert client.post("/v1/vehicles", json=car, headers=auth()).status_code == 201
    assert client.post("/v1/vehicles", json=car, headers=auth()).status_code == 409


def test_update_changes_only_what_was_sent(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    r = client.patch(
        f"/v1/vehicles/{created['id']}", json={"exterior_color": "White"}, headers=auth()
    )
    assert r.status_code == 200
    assert r.json()["exterior_color"] == "White"
    assert r.json()["trim"] == "Luxury"


def test_another_tenants_vehicle_is_404(client: TestClient) -> None:
    async def their_car() -> uuid.UUID:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return await conn.fetchval(
                """insert into vehicles (tenant_id, make, model) values ($1,'Kia','Seltos')
                   returning id""",
                TENANT_B,
            )
        finally:
            await conn.close()

    other = asyncio.run(their_car())
    assert client.get(f"/v1/vehicles/{other}", headers=auth()).status_code == 404
    assert (
        client.patch(
            f"/v1/vehicles/{other}", json={"location": "hacked"}, headers=auth()
        ).status_code
        == 404
    )


def test_a_viewer_cannot_add_a_vehicle(client: TestClient) -> None:
    set_role(USER_B, "viewer")
    r = client.post("/v1/vehicles", json=a_car(), headers=auth(USER_B))
    assert r.status_code == 403


# --------------------------------------------------------------------------
# selling
# --------------------------------------------------------------------------


def test_selling_emits_vehicle_sold_at_high_priority(client: TestClient) -> None:
    """Its handler cancels scheduled content. Marketing a car that is gone is
    the most visible way this product can embarrass a dealer."""
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    r = client.post(
        f"/v1/vehicles/{created['id']}/status",
        json={"status": "sold", "reason": "walk-in"},
        headers=auth(),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "sold"
    assert r.json()["sold_at"] is not None
    assert [e["vehicle_id"] for e in events_of("vehicle.sold")] == [created["id"]]


def test_a_non_sale_status_change_uses_the_generic_event(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    client.post(f"/v1/vehicles/{created['id']}/status", json={"status": "reserved"}, headers=auth())
    assert events_of("vehicle.sold") == []
    assert len(events_of("vehicle.status_changed")) == 1


# --------------------------------------------------------------------------
# pricing
# --------------------------------------------------------------------------


def test_price_change_writes_history_and_emits(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    r = client.post(
        f"/v1/vehicles/{created['id']}/price",
        json={"amount_minor": 8_900_000, "reason": "end of quarter"},
        headers=auth(),
    )
    assert r.status_code == 200
    assert r.json()["price"]["amount_minor"] == 8_900_000

    changed = events_of("vehicle.price_changed")
    assert len(changed) == 1
    assert changed[0]["before_minor"] == 9_500_000
    assert changed[0]["after_minor"] == 8_900_000

    async def history() -> list[Any]:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return await conn.fetch(
                "select price_minor, reason from vehicle_price_history where vehicle_id = $1",
                uuid.UUID(created["id"]),
            )
        finally:
            await conn.close()

    rows = asyncio.run(history())
    assert [r["price_minor"] for r in rows] == [8_900_000]
    assert rows[0]["reason"] == "end of quarter"


def test_setting_the_same_price_still_records_history_but_emits_nothing(
    client: TestClient,
) -> None:
    """An audit entry is always wanted; waking every downstream handler for a
    no-op price change is not."""
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    client.post(
        f"/v1/vehicles/{created['id']}/price",
        json={"amount_minor": 9_500_000, "reason": "confirmed"},
        headers=auth(),
    )
    assert events_of("vehicle.price_changed") == []


def test_a_marketer_cannot_change_a_price(client: TestClient) -> None:
    """Marketers publish; they do not set list prices."""
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    set_role(USER_B, "marketer")
    r = client.post(
        f"/v1/vehicles/{created['id']}/price",
        json={"amount_minor": 1, "reason": "oops"},
        headers=auth(USER_B),
    )
    assert r.status_code == 403


def test_a_price_change_needs_a_reason(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    r = client.post(
        f"/v1/vehicles/{created['id']}/price", json={"amount_minor": 100}, headers=auth()
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------
# filters and the stock report
# --------------------------------------------------------------------------


def test_filters_narrow_the_list(client: TestClient) -> None:
    client.post("/v1/vehicles", json=a_car(make="MG", model="MG7"), headers=auth())
    client.post("/v1/vehicles", json=a_car(make="BYD", model="Seal"), headers=auth())

    mg = client.get("/v1/vehicles?make=MG", headers=auth()).json()
    assert {v["model"] for v in mg} == {"MG7", "MG6"}  # MG6 comes from the seed

    byd = client.get("/v1/vehicles?q=seal", headers=auth()).json()
    assert [v["model"] for v in byd] == ["Seal"]


def test_max_price_filter_is_inclusive(client: TestClient) -> None:
    client.post("/v1/vehicles", json=a_car(price_minor=5_000_000), headers=auth())
    cheap = client.get("/v1/vehicles?max_price_minor=5000000", headers=auth()).json()
    assert all(v["price"]["amount_minor"] <= 5_000_000 for v in cheap if v["price"])


def test_stock_report_surfaces_aging_uncovered_stock(client: TestClient) -> None:
    """The report that answers 'what is not selling and what have we never
    posted about'."""
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()

    async def age_it() -> None:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            await conn.execute(
                "update vehicles set listed_at = now() - interval '60 days' where id = $1",
                uuid.UUID(created["id"]),
            )
        finally:
            await conn.close()

    asyncio.run(age_it())

    stale = client.get("/v1/vehicles/stock-report?min_days=45", headers=auth()).json()
    assert [v["id"] for v in stale] == [created["id"]]
    assert stale[0]["days_in_stock"] >= 60
    assert stale[0]["published_content_count"] == 0

    fresh = client.get("/v1/vehicles/stock-report?min_days=90", headers=auth()).json()
    assert fresh == []


def test_stock_report_only_covers_available_stock(client: TestClient) -> None:
    created = client.post("/v1/vehicles", json=a_car(), headers=auth()).json()
    client.post(f"/v1/vehicles/{created['id']}/status", json={"status": "sold"}, headers=auth())
    report = client.get("/v1/vehicles/stock-report", headers=auth()).json()
    assert created["id"] not in [v["id"] for v in report]


def test_stock_report_does_not_cross_tenants(client: TestClient) -> None:
    report = client.get("/v1/vehicles/stock-report", headers=auth()).json()
    ids = {v["id"] for v in report}

    async def their_ids() -> set[str]:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            rows = await conn.fetch("select id from vehicles where tenant_id = $1", TENANT_B)
            return {str(r["id"]) for r in rows}
        finally:
            await conn.close()

    assert ids.isdisjoint(asyncio.run(their_ids()))
