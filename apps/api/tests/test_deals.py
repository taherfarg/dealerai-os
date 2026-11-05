"""Lifecycle L6: the deal desk.

The exit criterion is the spine of this file: an offer below the floor cannot
be sent, and a deposit reserves the car and stops its marketing. Around it, the
rest of how Pollux's buyers pay — in stages, often from abroad, often in
another currency — and who may record that they did.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
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
from dealerai.events.handlers.lifecycle import on_vehicle_sold, on_vehicle_status_changed
from dealerai.lifecycle import deals
from dealerai.lifecycle.deals import Line, ReceiptReading, cleared, schedule, verify_receipt
from dealerai.main import app

AED = 100

# --------------------------------------------------------------------------
# the rules — pure
# --------------------------------------------------------------------------

INVOICE = [
    Line("vehicle", 200_000 * AED),
    Line("fee", 1_000 * AED),
    Line("freight", 6_000 * AED),
    Line("duties", 2_000 * AED),
]


def test_an_invoice_is_paid_in_three_stages() -> None:
    """The deposit is part of the price; the balance is the rest of the price
    and fees; logistics is freight and duties."""
    plan = schedule(INVOICE, 20_000 * AED, {})
    assert plan.due == {
        "deposit": 20_000 * AED,
        "balance": 181_000 * AED,
        "logistics": 8_000 * AED,
    }
    assert plan.total_minor == 209_000 * AED
    assert plan.next_stage == "deposit"


def test_the_next_payment_is_for_the_first_stage_still_owed() -> None:
    plan = schedule(INVOICE, 20_000 * AED, {"deposit": 20_000 * AED, "balance": 100_000 * AED})
    assert plan.next_stage == "balance"
    assert plan.left("balance") == 81_000 * AED
    assert plan.outstanding_minor == 89_000 * AED


def test_a_deposit_larger_than_the_price_is_not_a_deposit() -> None:
    with pytest.raises(ValueError, match="more than the price"):
        schedule(INVOICE, 202_000 * AED, {})


@pytest.mark.parametrize(
    ("price", "floor", "approved", "ok"),
    [
        (235_000, 211_000, None, True),  # over the floor
        (211_000, 211_000, None, True),  # at it
        (205_000, 211_000, None, False),  # under, nobody approved
        (205_000, 211_000, 205_000, True),  # under, approved at exactly this
        (204_000, 211_000, 205_000, False),  # under, approved at another figure
        (100_000, None, None, True),  # no floor set
    ],
)
def test_a_price_under_the_floor_is_cleared_only_at_the_approved_figure(
    price: int, floor: int | None, approved: int | None, ok: bool
) -> None:
    assert cleared(price, floor, approved) is ok


def _receipt(**over: Any) -> ReceiptReading:
    base: dict[str, Any] = {
        "amount": "5,450.00",
        "amount_quote": ":32A:261104USD5,450.00",
        "currency": "usd",
        "paid_on": "2026-11-04",
        "reference": "UETR 7f1c2a90",
        "reference_quote": "Reference: UETR 7f1c2a90",
        "payer": "SARL ATLAS AUTO",
        "bank": "BNA Alger",
    }
    return ReceiptReading(**{**base, **over})


def test_a_transfer_receipt_is_read_as_printed() -> None:
    proposal = verify_receipt(_receipt())
    assert (proposal.amount_minor, proposal.currency) == (545_000, "USD")
    assert proposal.reference == "UETR 7f1c2a90"
    assert proposal.fx_rate is None, "no rate printed, none invented"
    assert proposal.warnings == []


def test_an_amount_not_on_its_own_line_is_not_proposed() -> None:
    proposal = verify_receipt(_receipt(amount_quote=":71F:USD25,00"))
    assert proposal.amount_minor is None
    assert proposal.warnings == ["5,450.00 does not appear in the line it was read from"]


def test_a_printed_rate_is_kept_only_where_it_was_read() -> None:
    kept = verify_receipt(_receipt(fx_rate="3.6725", fx_quote="Rate 3.6725"))
    dropped = verify_receipt(_receipt(fx_rate="3.6725", fx_quote="Charges OUR"))
    assert kept.fx_rate == Decimal("3.6725")
    assert dropped.fx_rate is None


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


async def _car(su: asyncpg.Connection, *, status: str = "available") -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, model_year, price_minor,
                                 min_price_minor, status)
           values ($1, $2, 'Toyota', 'Hilux Travo', 2026, 21000000, 19500000, $3)""",
        vehicle_id,
        TENANT_A,
        status,
    )
    await su.execute(
        """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                      fx_rate, amount_tenant_minor, incurred_at)
           values ($1, $2, 'purchase', 18000000, 'AED', 1, 18000000, current_date)""",
        TENANT_A,
        vehicle_id,
    )
    return vehicle_id


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


ORDER: dict[str, Any] = {
    "buyer_name": "SARL Atlas Auto",
    "purchase_type": "export",
    "destination": "dz",
    "price_minor": 210_000 * AED,
    "deposit_minor": 20_000 * AED,
    "charges": [
        {
            "kind": "fee",
            "description": "Export plates and certificate",
            "amount_minor": 1_500 * AED,
        },
        {
            "kind": "freight",
            "description": "RoRo Jebel Ali to Algiers",
            "amount_minor": 6_000 * AED,
        },
    ],
}


def _quote(
    client: TestClient, car: uuid.UUID, who: uuid.UUID = SALES_1, **over: Any
) -> dict[str, Any]:
    response = client.post(f"/v1/vehicles/{car}/orders", json={**ORDER, **over}, headers=auth(who))
    assert response.status_code == 201, response.text
    return dict(response.json())


def _pay(
    client: TestClient,
    order_id: str,
    stage: str,
    amount: int,
    who: uuid.UUID = MANAGER,
    **over: Any,
) -> Any:
    return client.post(
        f"/v1/orders/{order_id}/payments",
        json={
            "stage": stage,
            "amount_minor": amount,
            "currency": "AED",
            "received_on": "2026-11-04",
            **over,
        },
        headers=auth(who),
    )


def _vehicle_status(client: TestClient, car: uuid.UUID) -> str:
    return str(client.get(f"/v1/vehicles/{car}", headers=auth(OWNER)).json()["status"])


def test_a_salesperson_quotes_and_cannot_take_money(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    assert order["cleared"] is True and order["status"] == "quoted"
    assert order["destination"] == "DZ"
    assert [c["kind"] for c in order["charges"]] == ["vehicle", "fee", "freight"]
    assert order["schedule"]["total"]["amount_minor"] == 217_500 * AED
    assert _pay(client, order["id"], "deposit", 20_000 * AED, who=SALES_1).status_code == 403


def test_an_offer_below_the_floor_cannot_be_taken_against(
    client: TestClient, car: uuid.UUID
) -> None:
    """The exit criterion's first half."""
    order = _quote(client, car, price_minor=190_000 * AED)
    assert order["cleared"] is False
    assert order["approval_id"] is not None

    refused = _pay(client, order["id"], "deposit", 20_000 * AED)
    assert refused.status_code == 409
    assert _vehicle_status(client, car) == "available"

    queue = client.get("/v1/approvals", headers=auth(OWNER)).json()
    [approval] = [a for a in queue if a["kind"] == "price_below_floor"]
    assert approval["summary"] == (
        "2026 Toyota Hilux Travo · SARL Atlas Auto · AED 190,000 · floor AED 195,000"
    )
    assert approval["required_role"] == "admin"
    decide = f"/v1/approvals/{approval['id']}/approve"
    assert client.post(decide, json={}, headers=auth(MANAGER)).status_code == 403


def test_a_deposit_reserves_the_car(client: TestClient, car: uuid.UUID) -> None:
    """The exit criterion's second half — its marketing is the worker's, below."""
    order = _quote(client, car)
    part = _pay(client, order["id"], "deposit", 5_000 * AED).json()
    assert part["status"] == "quoted", "part of a deposit holds nothing"
    held = _pay(client, order["id"], "deposit", 15_000 * AED).json()
    assert held["status"] == "reserved"
    assert held["schedule"]["next_stage"] == "balance"
    assert _vehicle_status(client, car) == "reserved"


def test_a_held_car_cannot_be_held_by_a_second_buyer(client: TestClient, car: uuid.UUID) -> None:
    first = _quote(client, car)
    second = _quote(client, car, buyer_name="Ahmed Benali")
    _pay(client, first["id"], "deposit", 20_000 * AED)
    refused = _pay(client, second["id"], "deposit", 20_000 * AED)
    assert refused.status_code == 409


def test_a_dollar_deposit_is_counted_in_dirhams(client: TestClient, car: uuid.UUID) -> None:
    """USD 5,450.00 at the peg is AED 20,015.125 — half to even, once: 20,015.12."""
    order = _quote(client, car)
    without = _pay(client, order["id"], "deposit", 545_000, currency="USD")
    assert without.status_code == 422, "a foreign payment needs its rate"
    held = _pay(client, order["id"], "deposit", 545_000, currency="USD", fx_rate="3.6725").json()
    [payment] = held["payments"]
    assert payment["amount"] == {"amount_minor": 545_000, "currency": "USD"}
    assert payment["amount_tenant"] == {"amount_minor": 2_001_512, "currency": "AED"}
    assert held["status"] == "reserved"


def test_sold_is_when_every_line_is_paid(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    _pay(client, order["id"], "deposit", 20_000 * AED)
    early = client.post(f"/v1/orders/{order['id']}/complete", headers=auth(MANAGER))
    assert early.status_code == 409
    _pay(client, order["id"], "balance", 191_500 * AED)
    _pay(client, order["id"], "logistics", 6_000 * AED)
    done = client.post(f"/v1/orders/{order['id']}/complete", headers=auth(MANAGER))
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    assert _vehicle_status(client, car) == "sold"
    assert asyncio.run(_completions()) == [order["id"]], "the after-sale check-in is booked (L8)"


async def _completions() -> list[str]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        rows = await conn.fetch(
            "select payload->>'order_id' as id from events where event_type = 'order.completed'"
        )
        return [row["id"] for row in rows]
    finally:
        await conn.close()


def test_letting_go_of_a_held_car_is_the_cashiers_call(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    _pay(client, order["id"], "deposit", 20_000 * AED)
    url = f"/v1/orders/{order['id']}/cancel"
    assert (
        client.post(url, json={"reason": "buyer withdrew"}, headers=auth(SALES_1)).status_code
        == 403
    )
    cancelled = client.post(url, json={"reason": "buyer withdrew"}, headers=auth(MANAGER)).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["schedule"]["paid"]["amount_minor"] == 20_000 * AED, "what was paid stays"
    assert _vehicle_status(client, car) == "available"


def test_a_held_order_is_not_requoted(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    _pay(client, order["id"], "deposit", 20_000 * AED)
    response = client.patch(
        f"/v1/orders/{order['id']}", json={"price_minor": 1}, headers=auth(SALES_1)
    )
    assert response.status_code == 409


def test_requoting_under_the_floor_asks_again(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    requoted = client.patch(
        f"/v1/orders/{order['id']}", json={"price_minor": 190_000 * AED}, headers=auth(SALES_1)
    ).json()
    assert requoted["cleared"] is False and requoted["approval_id"] is not None


@pytest.mark.parametrize(
    "over",
    [
        {"destination": None},  # an export with nowhere to go
        {"deposit_minor": 250_000 * AED},  # more than the price
    ],
)
def test_an_order_that_makes_no_sense_is_refused(
    client: TestClient, car: uuid.UUID, over: dict[str, Any]
) -> None:
    response = client.post(
        f"/v1/vehicles/{car}/orders", json={**ORDER, **over}, headers=auth(SALES_1)
    )
    assert response.status_code == 422


def test_a_car_that_is_sold_is_not_quoted(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    _pay(client, order["id"], "deposit", 20_000 * AED)
    response = client.post(f"/v1/vehicles/{car}/orders", json=ORDER, headers=auth(SALES_1))
    assert response.status_code == 409


def test_the_margin_on_an_order_is_buy_side(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    seen = client.get(f"/v1/orders/{order['id']}", headers=auth(OWNER)).json()
    assert seen["margin"] == {"amount_minor": 30_000 * AED, "currency": "AED"}
    assert client.get(f"/v1/orders/{order['id']}", headers=auth(SALES_1)).json()["margin"] is None


# --------------------------------------------------------------------------
# reading a transfer receipt
# --------------------------------------------------------------------------

READING: dict[str, Any] = {
    "amount": "5,450.00",
    "amount_quote": ":32A:261104USD5,450.00",
    "currency": "USD",
    "paid_on": "2026-11-04",
    "reference": "UETR 7f1c2a90",
    "reference_quote": "Reference: UETR 7f1c2a90",
    "payer": "SARL ATLAS AUTO",
    "bank": "BNA Alger",
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
                    prompt_token_count=900, candidates_token_count=120, total_token_count=1020
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


def test_reading_a_receipt_proposes_a_payment_and_records_none(
    client: TestClient, car: uuid.UUID, model: list[Any]
) -> None:
    order = _quote(client, car)
    response = client.post(
        f"/v1/orders/{order['id']}/payments/read",
        files={"file": ("swift.jpg", _jpeg(), "image/jpeg")},
        headers=auth(MANAGER),
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["amount"] == {"amount_minor": 545_000, "currency": "USD"}
    assert proposal["stage"] == "deposit"
    assert proposal["needs_fx_rate"] is True
    assert proposal["document_path"].startswith(f"{TENANT_A}/payments/")
    assert client.get(f"/v1/orders/{order['id']}", headers=auth(OWNER)).json()["payments"] == []


def test_a_receipt_from_somewhere_else_is_refused(client: TestClient, car: uuid.UUID) -> None:
    order = _quote(client, car)
    response = _pay(
        client, order["id"], "deposit", 20_000 * AED, document_path=f"{uuid.uuid4()}/payments/x.pdf"
    )
    assert response.status_code == 422


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


async def _content(su: asyncpg.Connection, vehicle_id: uuid.UUID, status: str) -> uuid.UUID:
    item: uuid.UUID = await su.fetchval(
        """insert into content_items (tenant_id, vehicle_id, kind, status)
           values ($1, $2, 'post', $3) returning id""",
        TENANT_A,
        vehicle_id,
        status,
    )
    return item


async def test_a_reserved_car_stops_being_marketed(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    scheduled = await _content(su, vehicle_id, "scheduled")
    draft = await _content(su, vehicle_id, "draft")
    published = await _content(su, vehicle_id, "published")
    await on_vehicle_status_changed(
        _event("vehicle.status_changed", {"vehicle_id": str(vehicle_id), "status": "reserved"})
    )
    rows = {
        r["id"]: (r["status"], r["rejection_reason"])
        for r in await su.fetch("select id, status, rejection_reason from content_items")
    }
    assert rows[scheduled] == ("archived", "the car is reserved")
    assert rows[draft] == ("archived", "the car is reserved")
    assert rows[published] == ("published", None), "a published post is the dealer's to take down"
    note = await su.fetchrow(
        "select user_id, title, href from notifications where kind = 'marketing_stopped'"
    )
    assert note["user_id"] == USER_A
    assert note["title"] == "A published post advertises a car that is reserved"
    assert note["href"] == f"/inventory/{vehicle_id}"


async def test_a_sold_car_stops_being_marketed_too(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    scheduled = await _content(su, vehicle_id, "scheduled")
    await on_vehicle_sold(_event("vehicle.sold", {"vehicle_id": str(vehicle_id), "status": "sold"}))
    assert (
        await su.fetchval("select status from content_items where id = $1", scheduled) == "archived"
    )


async def test_a_car_back_on_sale_stops_nothing(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    scheduled = await _content(su, vehicle_id, "scheduled")
    await on_vehicle_status_changed(
        _event("vehicle.status_changed", {"vehicle_id": str(vehicle_id), "status": "available"})
    )
    assert (
        await su.fetchval("select status from content_items where id = $1", scheduled)
        == "scheduled"
    )


async def test_an_approved_price_clears_that_price_and_no_other(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    vehicle_id = await _car(su)
    async with session.tenant_session(TENANT_A) as conn:
        order_id = await conn.fetchval(
            """insert into sale_orders (tenant_id, vehicle_id, buyer_name, purchase_type,
                                        currency, deposit_minor)
               values ($1, $2, 'Walk-in', 'local', 'AED', 1000000) returning id""",
            TENANT_A,
            vehicle_id,
        )
        await deals.write_charges(conn, TENANT_A, order_id, 190_000 * AED, [])
        order = await deals.load_order(conn, order_id)
        assert order is not None
        approval_id = await deals.ask_if_under_floor(conn, TENANT_A, order, currency="AED")
    assert approval_id is not None

    await su.execute(
        "update approvals set status = 'approved', decided_by = $2 where id = $1",
        approval_id,
        USER_A,
    )
    async with session.tenant_session(TENANT_A) as conn:
        assert await deals.apply_decision(conn, approval_id) == "applied"
        cleared_now = await deals.load_order(conn, order_id)
        assert cleared_now is not None and cleared_now.cleared
        await deals.write_charges(conn, TENANT_A, order_id, 185_000 * AED, [])
        moved = await deals.load_order(conn, order_id)
        assert moved is not None and not moved.cleared, "a lower price needs approving again"
