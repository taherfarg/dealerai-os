"""Lifecycle L5: appraisal and sourcing.

The exit criterion is the spine of this file: the buying list names cars
customers asked for this month that the dealer does not have. Around it, the
reader that turns a customer's words into those cars, the bid arithmetic, and
who may see any of it.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from PIL import Image

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, reseed_with_people
from dealerai.ai import gateway
from dealerai.config import get_settings
from dealerai.core.security import AuthedUser, mint_test_token
from dealerai.deps import TenantContext
from dealerai.events.bus import Event
from dealerai.events.handlers.lifecycle import on_interest_changed
from dealerai.lifecycle import sourcing
from dealerai.lifecycle.pricing import PricingSettings
from dealerai.lifecycle.sourcing import Car, Read, Worth, bid_from, max_bid, verify
from dealerai.main import app
from dealerai.routes.sourcing import AppraiseIn, appraise, buying_list

AED = 100
NOW = datetime.now(UTC)

# --------------------------------------------------------------------------
# the reader's output, checked in code — pure
# --------------------------------------------------------------------------


def test_a_car_is_kept_only_when_the_customers_words_name_it() -> None:
    words = "لاند كروزر ابيض 2025 أو باترول"
    read = Read(
        cars=[
            Car(make="Toyota", model="Land Cruiser", model_year=2025, quoted="لاند كروزر"),
            Car(make="Nissan", model="Patrol", quoted="باترول"),
            # The same car again, in other words: one want.
            Car(make="toyota", model="LAND CRUISER", quoted="لاند كروزر ابيض"),
            # Not in the words: the model's own idea.
            Car(make="Lexus", model="LX", quoted="LX 600"),
            Car(make="Kia", model="", quoted="باترول"),
        ]
    )
    kept = verify(read, words)
    assert [(c.make, c.model, c.model_year) for c in kept] == [
        ("Toyota", "Land Cruiser", 2025),
        ("Nissan", "Patrol", None),
    ]


def test_a_year_that_is_not_a_model_year_is_dropped_not_the_car() -> None:
    kept = verify(Read(cars=[Car(make="BYD", model="Seal", model_year=25, quoted="seal")]), "Seal")
    assert [(c.model, c.model_year) for c in kept] == [("Seal", None)]


# --------------------------------------------------------------------------
# the bid — pure
# --------------------------------------------------------------------------


def test_the_most_to_pay_keeps_the_target_margin_after_landing_and_holding() -> None:
    """A Land Cruiser that sells at AED 235,000 at the default 12%: it may land
    at AED 206,800. AED 8,000 of freight and customs, and 30 days at 8% on
    AED 206,800 (AED 1,359.79, rounded up), leave AED 197,440.21 — AED 197,000
    to the dealer's AED 500, rounded down."""
    bid = max_bid(
        235_000 * AED,
        currency="AED",
        settings=PricingSettings(),
        on_top_minor=8_000 * AED,
        days_to_sell=30,
    )
    assert bid.margin_minor == 28_200 * AED
    assert bid.holding_minor == 135_979
    assert bid.max_bid_minor == 197_000 * AED


def test_repairs_come_off_the_bid_and_a_car_the_costs_eat_is_worth_nothing() -> None:
    settings = PricingSettings()
    clean = max_bid(
        100_000 * AED, currency="AED", settings=settings, on_top_minor=0, days_to_sell=0
    )
    dented = max_bid(
        100_000 * AED,
        currency="AED",
        settings=settings,
        on_top_minor=0,
        days_to_sell=0,
        repairs_minor=3_000 * AED,
    )
    assert (clean.max_bid_minor, dented.max_bid_minor) == (88_000 * AED, 85_000 * AED)
    eaten = max_bid(
        10_000 * AED, currency="AED", settings=settings, on_top_minor=20_000 * AED, days_to_sell=0
    )
    assert eaten.max_bid_minor == 0


def test_what_a_person_typed_wins_and_no_price_means_no_bid() -> None:
    settings = PricingSettings()
    assert bid_from(Worth(), currency="AED", settings=settings) is None

    typed = bid_from(Worth(), currency="AED", settings=settings, expected_price_minor=100_000 * AED)
    assert typed is not None
    assert (typed.price_from, typed.on_top_from, typed.days_from) == ("typed", "assumed", "assumed")
    assert typed.days_to_sell == 45, "no history: the age the dealer already calls old"

    sold = Worth(sold=3, price_minor=235_000 * AED, on_top_minor=8_000 * AED, days_to_sell=30)
    both = bid_from(sold, currency="AED", settings=settings, expected_price_minor=240_000 * AED)
    assert both is not None
    assert (both.expected_price_minor, both.price_from, both.on_top_from) == (
        240_000 * AED,
        "typed",
        "history",
    )


# --------------------------------------------------------------------------
# the trigger and the reader, against the database
# --------------------------------------------------------------------------


def _profile(text: str | None, *, when: datetime = NOW, **more: Any) -> str:
    profile: dict[str, Any] = {}
    if text is not None:
        profile["interest"] = {
            "value": text,
            "source": "ai",
            "evidence_message_id": None,
            "updated_at": when.isoformat(),
        }
    for key, value in more.items():
        profile[key] = {"value": value, "source": "human", "updated_at": when.isoformat()}
    return json.dumps(profile)


async def _asks(
    su: asyncpg.Connection, contact_id: uuid.UUID, text: str | None, **more: Any
) -> None:
    await su.execute(
        "update contacts set profile = $2::jsonb where id = $1", contact_id, _profile(text, **more)
    )


async def _reads(su: asyncpg.Connection, contact_id: uuid.UUID) -> int:
    return int(
        await su.fetchval(
            """select count(*) from events where event_type = 'sourcing.interest_changed'
                and status = 'pending' and payload ->> 'contact_id' = $1""",
            str(contact_id),
        )
    )


class _Done:
    def __init__(self, parsed: Read) -> None:
        self.parsed = parsed
        self.cost_usd = 0.0


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The model, answering per interest from `answers`; every call in `calls`."""
    state: dict[str, Any] = {"answers": {}, "calls": [], "prompts": []}

    async def complete(*_: Any, messages: str, **__: Any) -> _Done:
        interest = messages.split("<untrusted>\n")[1].split("\n</untrusted>")[0]
        state["calls"].append(interest)
        state["prompts"].append(messages)
        return _Done(Read(cars=[Car(**car) for car in state["answers"].get(interest, [])]))

    monkeypatch.setattr(sourcing, "complete", complete)
    return state


async def _interest_changed(contact_id: uuid.UUID) -> None:
    await on_interest_changed(
        Event(1, TENANT_A, "sourcing.interest_changed", {"contact_id": str(contact_id)}, 1, None)
    )


async def test_an_interest_written_any_way_books_one_read(
    su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    customer = visibility_seed["s1"]
    await _asks(su, customer, "Land Cruiser 4.0, white")
    await _asks(su, customer, "Land Cruiser 4.0, white", budget={"amount_minor": 1})
    await _asks(su, customer, "Land Cruiser 2025")
    assert await _reads(su, customer) == 1, "one pending read per customer, however often"

    await su.execute("update events set status = 'done' where event_type like 'sourcing.%'")
    await _asks(su, customer, "Land Cruiser 2025", budget={"amount_minor": 2})
    assert await _reads(su, customer) == 0, "the budget changed, not what they asked for"


BACKFILL = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "0024_lifecycle_sourcing_backfill.sql"
)


async def test_interests_recorded_before_the_trigger_are_read_once(
    su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    """A dealership upgraded to L5 has customers who asked last week; the
    trigger never saw them. The backfill books their reads — once, and only
    for what the buying list's 30 days can show."""
    recent, old = visibility_seed["s1"], visibility_seed["s2"]
    await su.execute("alter table contacts disable trigger contacts_book_interest_read")
    try:
        await _asks(su, recent, "Land Cruiser 4.0, white")
        await _asks(su, old, "Patrol", when=NOW - timedelta(days=40))
    finally:
        await su.execute("alter table contacts enable trigger contacts_book_interest_read")
    assert await _reads(su, recent) == 0

    await su.execute(BACKFILL.read_text(encoding="utf-8"))
    await su.execute(BACKFILL.read_text(encoding="utf-8"))
    assert (await _reads(su, recent), await _reads(su, old)) == (1, 0)


async def test_an_interest_is_read_once_and_cleared_with_it(
    db: None,
    su: asyncpg.Connection,
    visibility_seed: dict[str, uuid.UUID],
    reader: dict[str, Any],
) -> None:
    customer = visibility_seed["s1"]
    await su.execute(
        """insert into vehicles (tenant_id, make, model, model_year, status)
           values ($1, 'Toyota', 'Land Cruiser', 2024, 'sold')""",
        TENANT_A,
    )
    reader["answers"]["لاند كروزر ابيض"] = [
        {"make": "Toyota", "model": "Land Cruiser", "quoted": "لاند كروزر"}
    ]
    await _asks(su, customer, "لاند كروزر ابيض")

    await _interest_changed(customer)
    await _interest_changed(customer)
    assert reader["calls"] == ["لاند كروزر ابيض"], "unchanged words are not read again"
    assert "- Toyota / Land Cruiser" in reader["prompts"][0], "the dealer's own spelling"
    row = await su.fetchrow("select make, model, quoted from customer_wants")
    assert dict(row) == {"make": "Toyota", "model": "Land Cruiser", "quoted": "لاند كروزر"}

    await _asks(su, customer, "a family SUV")
    await _interest_changed(customer)
    nothing = await su.fetch("select make, interest from customer_wants")
    assert [dict(r) for r in nothing] == [{"make": None, "interest": "a family SUV"}]

    await _asks(su, customer, None)
    await _interest_changed(customer)
    assert await su.fetchval("select count(*) from customer_wants") == 0


async def test_a_car_never_stocked_is_spelled_as_the_first_customer_who_asked_spelled_it(
    db: None,
    su: asyncpg.Connection,
    visibility_seed: dict[str, uuid.UUID],
    reader: dict[str, Any],
) -> None:
    """Two customers asking for a car the dealer has never had are one line on
    the buying list only if they are spelled alike: the second read is shown
    the first."""
    reader["answers"]["مرسيدس جي 63"] = [
        {"make": "Mercedes-Benz", "model": "G 63", "quoted": "مرسيدس جي 63"}
    ]
    await _asks(su, visibility_seed["s1"], "مرسيدس جي 63")
    await _interest_changed(visibility_seed["s1"])
    await _asks(su, visibility_seed["s2"], "G63 AMG black")
    await _interest_changed(visibility_seed["s2"])
    assert "- Mercedes-Benz / G 63" in reader["prompts"][1]


# --------------------------------------------------------------------------
# the exit criterion
# --------------------------------------------------------------------------


async def _car(
    su: asyncpg.Connection, make: str, model: str, status: str, *, cost: int | None = None
) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, model_year, status, listed_at)
           values ($1, $2, $3, $4, 2025, $5, now() - interval '30 days')""",
        vehicle_id,
        TENANT_A,
        make,
        model,
        status,
    )
    if cost is not None:
        await su.execute(
            """insert into vehicle_acquisitions (vehicle_id, tenant_id, source, purchased_at)
               values ($1, $2, 'dealer', current_date - 30)""",
            vehicle_id,
            TENANT_A,
        )
        await su.execute(
            """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                          fx_rate, amount_tenant_minor, incurred_at)
               values ($1, $2, 'purchase', $3, 'AED', 1, $3, current_date),
                      ($1, $2, 'shipping', 800000, 'AED', 1, 800000, current_date)""",
            TENANT_A,
            vehicle_id,
            cost,
        )
    return vehicle_id


async def _sold_for(su: asyncpg.Connection, vehicle_id: uuid.UUID, price: int) -> None:
    order_id = uuid.uuid4()
    await su.execute(
        "update vehicles set sold_at = now() - interval '20 days' where id = $1", vehicle_id
    )
    await su.execute(
        """insert into sale_orders (id, tenant_id, vehicle_id, buyer_name, purchase_type,
                                    currency, deposit_minor, status, completed_at, created_by)
           values ($1, $2, $3, 'Earlier buyer', 'local', 'AED', 0, 'completed',
                   now() - interval '20 days', $4)""",
        order_id,
        TENANT_A,
        vehicle_id,
        MANAGER,
    )
    await su.execute(
        """insert into sale_charges (tenant_id, order_id, kind, amount_minor, position)
           values ($1, $2, 'vehicle', $3, 0)""",
        TENANT_A,
        order_id,
        price,
    )


async def _wants(
    su: asyncpg.Connection,
    contact_id: uuid.UUID,
    make: str,
    model: str,
    quoted: str,
    *,
    days_ago: int = 3,
) -> None:
    await su.execute(
        """insert into customer_wants (tenant_id, contact_id, interest, make, model, quoted,
                                       asked_at)
           values ($1, $2, $3, $4, $5, $3, now() - make_interval(days => $6))""",
        TENANT_A,
        contact_id,
        quoted,
        make,
        model,
        days_ago,
    )


def _ctx(user: uuid.UUID, role: str) -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A, user=AuthedUser(id=user, email=None, claims={}), role=role
    )


async def test_the_buying_list_names_what_customers_asked_for_and_the_dealer_does_not_have(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    """The exit criterion. Two customers asked for a Land Cruiser — one in
    Arabic — and the dealer sold its last one, listed as a "Land Cruiser 4.0",
    twenty days ago; one asked for a Leopard 7, whose only one is held for
    another buyer. A "Seal Premium" is in stock, so a Seal is had; a Patrol was
    asked for forty days ago."""
    earlier = await _car(su, "Toyota", "Land Cruiser 4.0", "sold", cost=205_000 * AED)
    await _sold_for(su, earlier, 235_000 * AED)
    await _car(su, "BYD", "Leopard 7", "reserved")
    await _car(su, "BYD", "Seal Premium", "available")
    seed = visibility_seed
    await _asks(su, seed["s1"], None, budget={"amount_minor": 230_000 * AED, "currency": "AED"})
    await _asks(su, seed["x"], None, destination="DZ")
    await _wants(su, seed["s1"], "Toyota", "Land Cruiser", "لاند كروزر")
    await _wants(su, seed["x"], "toyota", "land cruiser", "Land Cruiser 4.0")
    await _wants(su, seed["x"], "Toyota", "Land Cruiser", "LC", days_ago=1)
    await _wants(su, seed["s2"], "BYD", "Leopard 7", "Leopard 7")
    await _wants(su, seed["covered"], "BYD", "Seal", "Seal")
    await _wants(su, seed["pool_local"], "Nissan", "Patrol", "Patrol", days_ago=40)

    made = await buying_list(_ctx(OWNER, "owner"))

    cars = [(car["make"], car["model"], len(car["askers"])) for car in made["cars"]]
    assert cars == [("Toyota", "Land Cruiser", 2), ("BYD", "Leopard 7", 1)]
    cruiser, leopard = made["cars"]
    assert {a["quoted"] for a in cruiser["askers"]} == {"لاند كروزر", "LC"}
    budgets = {a["destination"]: a["budget"] for a in cruiser["askers"]}
    assert budgets == {None: {"amount_minor": 230_000 * AED, "currency": "AED"}, "DZ": None}
    assert cruiser["worth"] == {
        "sold": 1,
        "price": {"amount_minor": 235_000 * AED, "currency": "AED"},
        "landed": {"amount_minor": 213_000 * AED, "currency": "AED"},
        "on_top": {"amount_minor": 8_000 * AED, "currency": "AED"},
        "days_to_sell": 10,
    }
    # AED 206,800 at 12%, less AED 8,000 on top and ten days' holding (AED 453.27).
    assert cruiser["bid"]["max_bid"] == {"amount_minor": 198_000 * AED, "currency": "AED"}
    assert leopard["bid"] is None, "never sold one: no bid"

    # The local team's manager sees the local team's customers asking.
    local = await buying_list(_ctx(MANAGER, "manager"))
    assert [(car["model"], len(car["askers"])) for car in local["cars"]] == [
        ("Land Cruiser", 1),
        ("Leopard 7", 1),
    ]


async def test_the_buying_list_and_an_appraisal_are_for_those_who_see_cost(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    """Called as the route function, the session is what the role clears: a
    viewer's has no buy side, so the dealer's history reads as nothing sold."""
    earlier = await _car(su, "Toyota", "Land Cruiser 4.0", "sold", cost=205_000 * AED)
    # The last one needed a bumper. That was its repair, not what landing one costs.
    await su.execute(
        """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                      fx_rate, amount_tenant_minor, incurred_at)
           values ($1, $2, 'repair', 300000, 'AED', 1, 300000, current_date)""",
        TENANT_A,
        earlier,
    )
    await _sold_for(su, earlier, 235_000 * AED)
    body = AppraiseIn(make=" toyota ", model="Land Cruiser", repairs_minor=2_000 * AED)

    seen = await appraise(body, _ctx(OWNER, "owner"))
    assert seen["worth"]["sold"] == 1
    assert seen["worth"]["landed"]["amount_minor"] == 216_000 * AED
    assert seen["worth"]["on_top"]["amount_minor"] == 8_000 * AED, "the bumper is not freight"
    assert seen["bid"]["repairs"] == {"amount_minor": 2_000 * AED, "currency": "AED"}
    assert seen["bid"]["max_bid"]["amount_minor"] == 196_000 * AED

    blind = await appraise(body, _ctx(OWNER, "viewer"))
    assert blind["worth"]["landed"] is None and blind["worth"]["on_top"] is None


# --------------------------------------------------------------------------
# the door — the API, per role, and a trade-in's photos
# --------------------------------------------------------------------------

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"

INSPECTION = {
    "findings": [
        {
            "photo": 1,
            "area": "exterior",
            "operation": "paint_panel",
            "quantity": 1,
            "severity": "minor",
            "description": "Repaint rear bumper",
            "seen": "scuffed corner",
        }
    ]
}


@pytest.fixture
def client(
    _migrated: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    asyncio.run(reseed_with_people())
    with TestClient(app) as c:
        yield c


def auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


@pytest.fixture
def vision(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    class Models:
        async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
            calls.append(kwargs)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model", parts=[types.Part(text=json.dumps(INSPECTION))]
                        ),
                        finish_reason=types.FinishReason.STOP,
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=900, candidates_token_count=100, total_token_count=1000
                ),
            )

    monkeypatch.setattr(
        gateway, "_client", type("C", (), {"aio": type("A", (), {"models": Models()})()})()
    )
    return calls


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (120, 120, 120)).save(buf, format="JPEG")
    return buf.getvalue()


def test_sourcing_is_buy_side(client: TestClient) -> None:
    for path in ("/v1/sourcing/buying-list",):
        assert client.get(path, headers=auth(SALES_1)).status_code == 403
        assert client.get(path, headers=auth(MANAGER)).status_code == 200
    body = {"make": "Toyota", "model": "Land Cruiser", "expected_price_minor": 100_000 * AED}
    assert client.post("/v1/sourcing/appraise", json=body, headers=auth(SALES_1)).status_code == 403
    typed = client.post("/v1/sourcing/appraise", json=body, headers=auth(MANAGER))
    assert typed.status_code == 200, typed.text
    assert typed.json()["bid"]["max_bid"]["amount_minor"] == 87_000 * AED, "45 days assumed"


def test_a_trade_ins_photos_are_read_into_priced_repairs_and_kept_nowhere(
    client: TestClient, vision: list[Any], tmp_path: Path
) -> None:
    client.put(
        "/v1/settings/recon", json={"rates": {"paint_panel": 900 * AED}}, headers=auth(OWNER)
    )
    response = client.post(
        "/v1/sourcing/inspect",
        files=[("files", ("rear.jpg", _jpeg(), "image/jpeg"))],
        data={
            "make": "Toyota",
            "model": "Land Cruiser",
            "model_year": "2023",
            "mileage_km": "41000",
        },
        headers=auth(MANAGER),
    )
    assert response.status_code == 200, response.text
    [paint] = response.json()["findings"]
    assert paint["estimate"] == {"amount_minor": 900 * AED, "currency": "AED"}
    assert paint["photo_path"] is None
    assert not any(tmp_path.rglob("*.jpg")), "an appraisal stores no photo"
    hint = [p.text for p in vision[0]["contents"].parts if p.text and "trade-in" in p.text]
    assert hint and "2023 Toyota Land Cruiser with 41,000 km" in hint[0]
