"""Lifecycle L2: what a car should be priced at, proposing it, and applying it.

The rules are pure and tested first. Then the loop as it runs: the morning
sweep proposes, a person approves, the price changes on the one path a price
changes on, and content that quoted the old figure is stopped.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, USER_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.db import session
from dealerai.events.bus import Event
from dealerai.events.handlers.lifecycle import after_price_change, on_pricing_sweep
from dealerai.events.handlers.runs import on_approval_decided
from dealerai.lifecycle.pricing import AgeStep, Facts, PricingSettings, recommend
from dealerai.main import app

AED = 100  # minor units per dirham

# --------------------------------------------------------------------------
# the rules — pure
# --------------------------------------------------------------------------


def facts(**over: Any) -> Facts:
    base: dict[str, Any] = {
        "status": "available",
        "currency": "AED",
        "tenant_currency": "AED",
        "price_minor": 235_000 * AED,
        "floor_minor": 211_000 * AED,
        "landed_minor": 200_000 * AED,
        "cost_lines": 3,
        "days_in_stock": 10,
        "leads_30d": 0,
    }
    return Facts(**{**base, **over})


DEFAULTS = PricingSettings()


def test_the_target_is_cost_plus_margin_on_the_price_rounded_up() -> None:
    """AED 200,000 at 12% on the price is 227,272.73 — rounded up to the next
    500, so the margin is never a fraction short of what the dealer asked."""
    rec = recommend(facts(price_minor=None), DEFAULTS)
    assert rec.target_minor == 227_500 * AED


def test_the_floor_keeps_its_own_margin() -> None:
    """5% on the price: 210,526.32, rounded up to 211,000."""
    rec = recommend(facts(price_minor=None, floor_minor=None), DEFAULTS)
    assert rec.floor_minor == 211_000 * AED


def test_an_unpriced_car_gets_a_price() -> None:
    rec = recommend(facts(price_minor=None), DEFAULTS)
    assert rec.action == "set_price"
    assert rec.price_minor == 227_500 * AED


def test_a_car_past_two_steps_of_the_ladder_is_proposed_down() -> None:
    """227,500 less 3% and 3% again is 214,054.75, rounded down to 214,000."""
    rec = recommend(facts(days_in_stock=60), DEFAULTS)
    assert rec.action == "reduce"
    assert rec.price_minor == 214_000 * AED
    assert rec.reasons[:3] == ["aged:45", "aged:60", "no_leads"]


def test_the_ladder_stops_at_the_floor() -> None:
    """A year in stock and every step taken: still never below the floor."""
    steep = PricingSettings(steps=[AgeStep(days=30, cut_bps=5_000)])
    rec = recommend(facts(days_in_stock=365), steep)
    assert rec.price_minor == 211_000 * AED


def test_customers_asking_means_the_price_is_not_the_problem() -> None:
    """Four leads in thirty days on a car aged sixty: hold. Cutting the price
    of a car people want gives away margin for a problem it does not have."""
    rec = recommend(facts(days_in_stock=60, leads_30d=4), DEFAULTS)
    assert rec.action == "hold"
    assert "demand:4" in rec.reasons


def test_the_demand_check_can_be_turned_off() -> None:
    rec = recommend(facts(days_in_stock=60, leads_30d=4), PricingSettings(hold_if_leads_30d=0))
    assert rec.action == "reduce"


def test_a_fresh_car_priced_above_target_is_left_alone() -> None:
    """Found by the sweep test: day five, priced above the target margin, and a
    cut was proposed. Only age moves a price down; headroom on a new arrival is
    the dealer's room to negotiate."""
    rec = recommend(facts(days_in_stock=5), DEFAULTS)
    assert rec.action == "hold"
    assert rec.reasons[0] == "above_target"


def test_a_price_already_at_or_under_the_ladder_holds() -> None:
    rec = recommend(facts(price_minor=220_000 * AED, days_in_stock=10), DEFAULTS)
    assert rec.action == "hold"
    assert rec.reasons[0] == "on_target"


def test_a_price_under_the_floor_is_reported_not_proposed() -> None:
    """Raising a published price is the dealer's call. The screen says so; the
    sweep does not put it in the queue."""
    rec = recommend(facts(price_minor=205_000 * AED), DEFAULTS)
    assert rec.action == "below_floor"
    assert rec.price_minor is None


def test_a_missing_floor_is_proposed_with_the_price() -> None:
    rec = recommend(facts(days_in_stock=60, floor_minor=None), DEFAULTS)
    assert rec.floor_minor == 211_000 * AED
    assert "floor_missing" in rec.reasons


def test_a_floor_under_the_margin_is_raised() -> None:
    rec = recommend(facts(days_in_stock=60, floor_minor=200_000 * AED), DEFAULTS)
    assert rec.floor_minor == 211_000 * AED
    assert "floor_low" in rec.reasons


def test_a_floor_the_dealer_set_higher_is_left_alone() -> None:
    """The dealer knows something the ladder does not."""
    rec = recommend(facts(days_in_stock=60, floor_minor=215_000 * AED), DEFAULTS)
    assert rec.floor_minor is None
    assert rec.action == "reduce"


@pytest.mark.parametrize(
    ("over", "action"),
    [
        ({"status": "sold"}, "not_for_sale"),
        ({"status": "reserved"}, "not_for_sale"),
        ({"cost_lines": 0, "landed_minor": 0}, "no_cost"),
        ({"currency": "USD"}, "other_currency"),
    ],
)
def test_nothing_is_priced_without_what_it_needs(over: dict[str, Any], action: str) -> None:
    rec = recommend(facts(**over), DEFAULTS)
    assert rec.action == action
    assert rec.price_minor is None


def test_a_three_decimal_currency_rounds_on_its_own_units() -> None:
    """KWD 500 is 500,000 fils. Rounding to 500 *minor units* would be half a dinar."""
    rec = recommend(
        facts(currency="KWD", tenant_currency="KWD", price_minor=None, landed_minor=20_000_000),
        DEFAULTS,
    )
    assert rec.price_minor is not None and rec.price_minor % 500_000 == 0


def test_steps_are_applied_in_age_order_however_they_were_saved() -> None:
    shuffled = PricingSettings(steps=[AgeStep(days=60, cut_bps=300), AgeStep(days=45, cut_bps=300)])
    assert recommend(facts(days_in_stock=60), shuffled).price_minor == 214_000 * AED


def test_a_floor_margin_above_the_target_is_refused() -> None:
    with pytest.raises(ValidationError, match="floor"):
        PricingSettings(target_margin_bps=500, floor_margin_bps=900)


# --------------------------------------------------------------------------
# the loop, against Postgres
# --------------------------------------------------------------------------


async def _car(
    su: asyncpg.Connection,
    *,
    price: int | None = 235_000 * AED,
    floor: int | None = 211_000 * AED,
    days: int = 60,
    landed: int = 200_000 * AED,
) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, model_year, price_minor,
                                 min_price_minor, listed_at)
           values ($1, $2, 'Toyota', 'Land Cruiser', 2024, $3, $4,
                   now() - make_interval(days => $5))""",
        vehicle_id,
        TENANT_A,
        price,
        floor,
        days,
    )
    await su.execute(
        """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                      fx_rate, amount_tenant_minor, incurred_at)
           values ($1, $2, 'purchase', $3, 'AED', 1, $3, current_date)""",
        TENANT_A,
        vehicle_id,
        landed,
    )
    return vehicle_id


def _event(event_type: str, payload: dict[str, Any]) -> Event:
    return Event(
        id=0,
        tenant_id=TENANT_A,
        event_type=event_type,
        payload=payload,
        attempts=1,
        dedupe_key=None,
    )


async def _sweep() -> None:
    await on_pricing_sweep(_event("pricing.sweep_due", {"date": "2026-11-04"}))


async def _approvals(su: asyncpg.Connection) -> list[asyncpg.Record]:
    return await su.fetch(
        "select id, entity_id, status, payload from approvals where kind = 'price_change'"
    )


async def _decide(su: asyncpg.Connection, approval_id: uuid.UUID, outcome: str) -> None:
    await su.execute(
        """update approvals set status = $2, decided_by = $3, decided_at = now()
            where id = $1""",
        approval_id,
        outcome,
        USER_A,
    )
    await on_approval_decided(
        _event(
            "approval.decided",
            {"approval_id": str(approval_id), "kind": "price_change", "decision": outcome},
        )
    )


async def test_the_sweep_proposes_what_should_move_and_nothing_else(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    aged = await _car(su, days=60)
    await _car(su, days=5)  # on target: holds
    await _sweep()

    proposals = await _approvals(su)
    assert [p["entity_id"] for p in proposals] == [aged]
    payload = json.loads(proposals[0]["payload"])
    assert payload["after_minor"] == 214_000 * AED
    assert payload["before_minor"] == 235_000 * AED
    assert (
        await su.fetchval("select summary from approvals where id = $1", proposals[0]["id"])
        == "2024 Toyota Land Cruiser · AED 235,000 → AED 214,000"
    )


async def test_a_second_sweep_does_not_nag(db: None, seeded: None, su: asyncpg.Connection) -> None:
    """One open proposal per car. Two for the same car and neither is decided."""
    await _car(su, days=60)
    await _sweep()
    await _sweep()
    assert len(await _approvals(su)) == 1


async def test_the_sweep_tells_whoever_may_change_prices_once(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    await _car(su, days=60)
    await _car(su, days=90)
    await _sweep()
    rows = await su.fetch("select user_id, title from notifications where kind = 'price_proposed'")
    assert [r["user_id"] for r in rows] == [USER_A], "the owner, once, not once per car"
    assert rows[0]["title"].startswith("2 price changes")


async def test_a_dealer_who_turned_it_off_gets_no_proposals(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    await su.execute(
        "update tenants set pricing_settings = $2 where id = $1",
        TENANT_A,
        json.dumps({"enabled": False}),
    )
    await _car(su, days=90)
    await _sweep()
    assert await _approvals(su) == []


async def test_approving_changes_the_price_on_the_one_path(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """History written with the approver's name, the floor set, and the event
    that tells the copilot and the content checks."""
    vehicle_id = await _car(su, days=60, floor=None)
    await _sweep()
    [proposal] = await _approvals(su)
    await _decide(su, proposal["id"], "approved")

    car = await su.fetchrow(
        "select price_minor, min_price_minor from vehicles where id = $1", vehicle_id
    )
    assert car is not None
    assert car["price_minor"] == 214_000 * AED
    assert car["min_price_minor"] == 211_000 * AED
    history = await su.fetchrow(
        "select actor_id, reason from vehicle_price_history where vehicle_id = $1", vehicle_id
    )
    assert history is not None and history["actor_id"] == str(USER_A)
    assert "aged:60" in history["reason"]
    event = await su.fetchrow(
        "select payload from events where event_type = 'vehicle.price_changed' "
        "order by id desc limit 1"
    )
    assert event is not None
    assert json.loads(event["payload"])["after_minor"] == 214_000 * AED


async def test_a_proposal_overtaken_by_a_hand_change_is_not_applied(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """Somebody repriced the car by hand after the proposal was made. Their
    decision is newer than the queue's."""
    vehicle_id = await _car(su, days=60)
    await _sweep()
    [proposal] = await _approvals(su)
    await su.execute(
        "update vehicles set price_minor = $2 where id = $1", vehicle_id, 225_000 * AED
    )

    await _decide(su, proposal["id"], "approved")
    price = await su.fetchval("select price_minor from vehicles where id = $1", vehicle_id)
    assert price == 225_000 * AED


async def test_rejecting_changes_nothing(db: None, seeded: None, su: asyncpg.Connection) -> None:
    vehicle_id = await _car(su, days=60)
    await _sweep()
    [proposal] = await _approvals(su)
    await _decide(su, proposal["id"], "rejected")
    assert await su.fetchval("select price_minor from vehicles where id = $1", vehicle_id) == (
        235_000 * AED
    )


async def _content(
    su: asyncpg.Connection, vehicle_id: uuid.UUID, caption: str, status: str
) -> uuid.UUID:
    item = await su.fetchval(
        """insert into content_items (tenant_id, vehicle_id, kind, status)
           values ($1, $2, 'post', $3) returning id""",
        TENANT_A,
        vehicle_id,
        status,
    )
    await su.execute(
        """insert into content_copy (tenant_id, content_item_id, locale, caption)
           values ($1, $2, 'en', $3)""",
        TENANT_A,
        item,
        caption,
    )
    return item


async def test_a_scheduled_post_quoting_the_old_price_is_stopped(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """The zero-tolerance failure, prevented the moment it becomes possible:
    a scheduled post that would publish a price the dealer no longer charges."""
    vehicle_id = await _car(su)
    stale = await _content(su, vehicle_id, "Yours for AED 235,000.", "scheduled")
    fine = await _content(su, vehicle_id, "Come and see it this weekend.", "scheduled")

    await after_price_change(
        _event(
            "vehicle.price_changed",
            {
                "vehicle_id": str(vehicle_id),
                "before_minor": 235_000 * AED,
                "after_minor": 214_000 * AED,
                "currency": "AED",
            },
        )
    )
    rows = {
        r["id"]: r for r in await su.fetch("select id, status, rejection_reason from content_items")
    }
    assert rows[stale]["status"] == "rejected"
    assert "AED 214,000" in rows[stale]["rejection_reason"]
    assert rows[fine]["status"] == "scheduled", "a post that names no price is fine"


async def test_a_published_post_quoting_the_old_price_is_named_to_the_owner(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """Nothing here can take a post down, so somebody who can is told."""
    vehicle_id = await _car(su)
    await _content(su, vehicle_id, "Yours for AED 235,000.", "published")
    await after_price_change(
        _event(
            "vehicle.price_changed",
            {
                "vehicle_id": str(vehicle_id),
                "before_minor": 235_000 * AED,
                "after_minor": 214_000 * AED,
                "currency": "AED",
            },
        )
    )
    note = await su.fetchrow("select user_id, href from notifications where kind = 'content_stale'")
    assert note is not None
    assert note["user_id"] == USER_A
    assert note["href"] == f"/inventory/{vehicle_id}"


async def test_the_sweep_reads_the_buy_side_a_salesperson_cannot(
    db: None, seeded: None, su: asyncpg.Connection
) -> None:
    """The recommendation needs the cost, and a salesperson's session reads
    none — so through their session it can only ever say no_cost."""
    from dealerai.lifecycle import pricing

    vehicle_id = await _car(su, days=60)
    async with session.tenant_session(TENANT_A, user_id=SALES_1, scope="own") as conn:
        seen = await pricing.facts_for(conn, vehicle_id)
    assert seen is not None and seen.cost_lines == 0


# --------------------------------------------------------------------------
# the API
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
        return await _car(conn, days=60)
    finally:
        await conn.close()


@pytest.fixture
def car(_migrated: None) -> uuid.UUID:
    return asyncio.run(_people_and_a_car())


@pytest.fixture
def client(car: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_the_recommendation_is_buy_side(client: TestClient, car: uuid.UUID) -> None:
    assert client.get(f"/v1/vehicles/{car}/pricing", headers=auth(SALES_1)).status_code == 403
    rec = client.get(f"/v1/vehicles/{car}/pricing", headers=auth(MANAGER)).json()
    assert rec["action"] == "reduce"
    assert rec["price"] == {"amount_minor": 214_000 * AED, "currency": "AED"}
    assert rec["pending_approval_id"] is None


def test_proposing_now_queues_it_once(client: TestClient, car: uuid.UUID) -> None:
    first = client.post(f"/v1/vehicles/{car}/pricing/propose", headers=auth(MANAGER)).json()
    assert first["approval_id"]
    second = client.post(f"/v1/vehicles/{car}/pricing/propose", headers=auth(MANAGER)).json()
    assert second["approval_id"] is None
    assert "already waiting" in second["note"]
    rec = client.get(f"/v1/vehicles/{car}/pricing", headers=auth(OWNER)).json()
    assert rec["pending_approval_id"] == first["approval_id"]


def test_a_manager_proposes_and_only_an_owner_or_admin_decides(
    client: TestClient, car: uuid.UUID
) -> None:
    """Changing a price stays where it was: admin and above. Proposing it is
    not changing it."""
    approval = client.post(f"/v1/vehicles/{car}/pricing/propose", headers=auth(MANAGER)).json()
    refused = client.post(
        f"/v1/approvals/{approval['approval_id']}/approve", json={}, headers=auth(MANAGER)
    )
    assert refused.status_code == 403
    allowed = client.post(
        f"/v1/approvals/{approval['approval_id']}/approve", json={}, headers=auth(OWNER)
    )
    assert allowed.status_code == 200


def test_pricing_settings_are_the_owners(client: TestClient, car: uuid.UUID) -> None:
    assert client.get("/v1/settings/pricing", headers=auth(MANAGER)).status_code == 403
    defaults = client.get("/v1/settings/pricing", headers=auth(OWNER)).json()
    assert defaults["target_margin_bps"] == 1_200
    saved = client.put(
        "/v1/settings/pricing",
        json={**defaults, "target_margin_bps": 1_500},
        headers=auth(OWNER),
    )
    assert saved.status_code == 200
    rec = client.get(f"/v1/vehicles/{car}/pricing", headers=auth(OWNER)).json()
    assert rec["target"]["amount_minor"] == 235_500 * AED, "200,000 / 0.85, rounded up"


def test_settings_that_make_no_sense_are_refused(client: TestClient, car: uuid.UUID) -> None:
    response = client.put(
        "/v1/settings/pricing",
        json={"target_margin_bps": 500, "floor_margin_bps": 900},
        headers=auth(OWNER),
    )
    assert response.status_code == 422
    assert "floor" in response.json()["detail"], "said in words, not as a failed field"
