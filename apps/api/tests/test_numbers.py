"""Lifecycle L8: after the sale, and the numbers.

The exit criterion is the spine of this file: the owner's morning brief says
what the month made and which cars are costing money to keep. Around it, the
arithmetic those numbers are made of, who may see them, and what happens to a
buyer once the car is theirs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

import asyncpg
import pytest

from conftest import MANAGER, OWNER, SALES_1, TENANT_A
from dealerai.agents.sales import brief as brief_agent
from dealerai.agents.sales.brief import Written
from dealerai.core.security import AuthedUser
from dealerai.deps import TenantContext
from dealerai.events.bus import Event
from dealerai.events.handlers.lifecycle import on_order_completed
from dealerai.events.handlers.manager import on_brief_due
from dealerai.guards import facts as facts_guard
from dealerai.lifecycle.numbers import (
    Business,
    Costly,
    Month,
    holding_minor,
    month_of,
    old_after,
    render,
    stock_of,
)
from dealerai.lifecycle.pricing import AgeStep, PricingSettings
from dealerai.routes.customers import get_customer
from dealerai.routes.dashboard import manager_dashboard
from dealerai.sales.clock import zone
from dealerai.sales.dashboard import Headline

AED = 100
DUBAI = zone("Asia/Dubai")
TODAY = datetime.now(DUBAI).date()

# --------------------------------------------------------------------------
# the arithmetic — pure
# --------------------------------------------------------------------------


def test_holding_is_the_money_tied_up_at_the_yearly_rate_plus_a_daily_amount() -> None:
    """AED 200,000 at 8% a year for 73 days — a fifth of a year — is AED 3,200."""
    assert holding_minor(200_000 * AED, 73, rate_bps=800, per_day_minor=0) == 3_200 * AED
    assert (
        holding_minor(200_000 * AED, 73, rate_bps=800, per_day_minor=50 * AED)
        == 3_200 * AED + 73 * 50 * AED
    )


def test_holding_rounds_up_and_starts_at_nothing() -> None:
    """One day is 4,383.56 fils, and never reads as less than it is."""
    assert holding_minor(200_000 * AED, 1, rate_bps=800, per_day_minor=0) == 4_384
    assert holding_minor(200_000 * AED, 0, rate_bps=800, per_day_minor=50 * AED) == 0


def test_a_car_is_old_from_the_first_step_of_the_dealers_own_ladder() -> None:
    assert old_after(PricingSettings()) == 45
    ladder = [AgeStep(days=90, cut_bps=500), AgeStep(days=30, cut_bps=200)]
    assert old_after(PricingSettings(steps=ladder)) == 30
    assert old_after(PricingSettings(steps=[])) == 45


def test_the_months_gross_counts_only_the_cars_with_a_cost() -> None:
    """A car sold with no cost recorded is sold, but its gross is unknown, not its price."""
    month = month_of(
        [
            {
                "price_minor": 210_000 * AED,
                "landed_cost_minor": 190_000 * AED,
                "cost_lines": 2,
                "days_held": 30,
            },
            {
                "price_minor": 100_000 * AED,
                "landed_cost_minor": 0,
                "cost_lines": 0,
                "days_held": 10,
            },
        ]
    )
    assert month == Month(
        sold=2, revenue_minor=310_000 * AED, gross_minor=20_000 * AED, costed=1, avg_days_held=20
    )
    assert month.gross_per_car_minor == 20_000 * AED


def _stock_row(model: str, *, landed: int, lines: int, days: int) -> dict[str, Any]:
    return {
        "vehicle_id": uuid.uuid4(),
        "currency": "AED",
        "price_minor": 215_000 * AED,
        "landed_cost_minor": landed,
        "cost_lines": lines,
        "days_held": days,
        "model_year": 2025,
        "make": "BYD",
        "model": model,
        "trim": None,
    }


def test_a_car_with_no_invoice_entered_still_costs_its_storage() -> None:
    """Storage is paid on a car whose invoice nobody has entered yet; it has no
    margin to speak of. With no daily amount it has cost nothing, and is not named."""
    rows = [
        _stock_row("Destroyer 05", landed=200_000 * AED, lines=1, days=73),
        _stock_row("Seal", landed=0, lines=0, days=60),
    ]
    daily = PricingSettings(holding_per_day_major=20)
    in_stock, tied_up, per_day, costly = stock_of(rows, currency="AED", settings=daily)
    assert (in_stock, tied_up) == (2, 200_000 * AED)
    assert per_day == 4_384 + 2 * 20 * AED
    seal = next(car for car in costly if car.label == "2025 BYD Seal")
    assert (seal.holding_minor, seal.margin_left_minor) == (60 * 20 * AED, None)

    _, _, _, costly = stock_of(rows, currency="AED", settings=PricingSettings())
    assert [car.label for car in costly] == ["2025 BYD Destroyer 05"]


BUSINESS = Business(
    currency="AED",
    month=Month(
        sold=1,
        revenue_minor=210_000 * AED,
        gross_minor=20_000 * AED,
        costed=1,
        avg_days_held=30,
    ),
    in_stock=3,
    tied_up_minor=600_000 * AED,
    holding_per_day_minor=132 * AED,
    old_after_days=45,
    costly=[
        Costly(
            vehicle_id=uuid.uuid4(),
            label="2025 BYD Destroyer 05",
            days_held=73,
            holding_minor=3_200 * AED,
            margin_left_minor=11_800 * AED,
        )
    ],
)


def test_a_headline_may_use_the_months_numbers_and_no_others() -> None:
    block = render(BUSINESS)
    assert "gross: AED 20,000" in block
    assert "- 2025 BYD Destroyer 05: 73 days, AED 3,200 to keep so far" in block
    line = "The month made AED 20,000 gross; the 2025 BYD Destroyer 05 has cost AED 3,200 to keep."
    assert facts_guard.check(line, facts=block) == []
    assert facts_guard.check("The month made AED 21,000.", facts=block), "a number nobody counted"


# --------------------------------------------------------------------------
# the brief and the dashboard
# --------------------------------------------------------------------------


class FakeBrief:
    def __init__(self) -> None:
        self.shown: list[str] = []

    async def write(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, facts: str) -> Written:
        self.shown.append(facts)
        return Written(Headline(en="The month made AED 20,000.", ar="إجمالي الربح 20,000."), 0.0)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBrief:
    model = FakeBrief()
    monkeypatch.setattr(brief_agent, "write", model.write)
    return model


async def _car(su: asyncpg.Connection, model: str, *, status: str, held_days: int) -> uuid.UUID:
    vehicle_id = uuid.uuid4()
    await su.execute(
        """insert into vehicles (id, tenant_id, make, model, model_year, price_minor, status,
                                 listed_at)
           values ($1, $2, 'BYD', $3, 2025, 21500000, $4, now() - make_interval(days => $5))""",
        vehicle_id,
        TENANT_A,
        model,
        status,
        held_days,
    )
    await su.execute(
        """insert into vehicle_acquisitions (vehicle_id, tenant_id, source, purchased_at)
           values ($1, $2, 'import', current_date - $3::int)""",
        vehicle_id,
        TENANT_A,
        held_days,
    )
    await su.execute(
        """insert into vehicle_costs (tenant_id, vehicle_id, category, amount_minor, currency,
                                      fx_rate, amount_tenant_minor, incurred_at)
           values ($1, $2, 'purchase', 20000000, 'AED', 1, 20000000, current_date)""",
        TENANT_A,
        vehicle_id,
    )
    return vehicle_id


async def _sold(
    su: asyncpg.Connection, when: datetime, *, lead_id: uuid.UUID | None = None, kind: str = "local"
) -> uuid.UUID:
    """A car bought for AED 190,000 and sold for AED 210,000, completed `when`."""
    vehicle_id = await _car(su, "Seal", status="sold", held_days=30)
    await su.execute(
        "update vehicle_costs set amount_minor = 19000000, amount_tenant_minor = 19000000 "
        "where vehicle_id = $1",
        vehicle_id,
    )
    await su.execute("update vehicles set sold_at = $2 where id = $1", vehicle_id, when)
    order_id = uuid.uuid4()
    await su.execute(
        """insert into sale_orders (id, tenant_id, vehicle_id, lead_id, buyer_name, purchase_type,
                                    destination, currency, deposit_minor, status, completed_at,
                                    created_by)
           values ($1, $2, $3, $4, 'SARL Atlas Auto', $5, $6, 'AED', 2000000, 'completed', $7,
                   $8)""",
        order_id,
        TENANT_A,
        vehicle_id,
        lead_id,
        kind,
        "DZ" if kind == "export" else None,
        when,
        MANAGER,
    )
    await su.execute(
        """insert into sale_charges (tenant_id, order_id, kind, amount_minor, position)
           values ($1, $2, 'vehicle', 21000000, 0), ($1, $2, 'freight', 600000, 1)""",
        TENANT_A,
        order_id,
    )
    return order_id


async def _brief_due() -> None:
    await on_brief_due(Event(1, TENANT_A, "sales.brief_due", {"date": TODAY.isoformat()}, 1, None))


def _ctx(user: uuid.UUID, role: str) -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A, user=AuthedUser(id=user, email=None, claims={}), role=role
    )


async def test_the_owners_brief_says_what_the_month_made_and_what_costs_money_to_keep(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID], fake: FakeBrief
) -> None:
    """The exit criterion. A car sold yesterday for AED 210,000 that cost
    AED 190,000, and one held 73 days on AED 200,000 at the default 8%."""
    yesterday_noon = datetime.combine(TODAY - timedelta(days=1), time(12), tzinfo=DUBAI)
    await _sold(su, yesterday_noon)
    await _car(su, "Destroyer 05", status="available", held_days=73)
    await _car(su, "Dolphin", status="available", held_days=10)

    await _brief_due()

    assert fake.shown, "a selling month is worth a headline on a quiet day"
    block = fake.shown[0]
    assert (
        "- cars sold: 1; their price: AED 210,000; gross: AED 20,000; gross per car: AED 20,000"
        in block
    ), "freight is the buyer's, not profit"
    assert "## Costing money to keep (held over 45 days)" in block
    assert (
        "- 2025 BYD Destroyer 05: 73 days, AED 3,200 to keep so far;"
        " margin left at list: AED 11,800"
    ) in block
    assert "Dolphin" not in block.split("## Costing money to keep")[1], "ten days is not old"
    headline = await su.fetchval("select headline from sales_briefs where user_id = $1", OWNER)
    assert headline is not None and "20,000" in headline


async def test_the_business_is_shown_only_to_those_cleared_for_cost(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    await _sold(su, datetime.now(UTC))
    await _car(su, "Destroyer 05", status="available", held_days=73)

    board = await manager_dashboard(_ctx(MANAGER, "manager"), None)
    made = board["business"]
    assert made["month"]["sold"] == 1
    assert made["month"]["gross"] == {"amount_minor": 20_000 * AED, "currency": "AED"}
    assert made["in_stock"] == await su.fetchval(
        "select count(*) from vehicles"
        " where tenant_id = $1 and status in ('draft', 'available', 'reserved')",
        TENANT_A,
    ), "this dealer's cars, not the other tenant's"
    assert made["tied_up"]["amount_minor"] == 200_000 * AED, "only the car with a cost"
    [costly] = made["costly"]
    assert (costly["label"], costly["days_held"]) == ("2025 BYD Destroyer 05", 73)

    blind = await manager_dashboard(_ctx(OWNER, "viewer"), None)
    assert blind["business"] is None


# --------------------------------------------------------------------------
# after the sale
# --------------------------------------------------------------------------


async def _lead_of(su: asyncpg.Connection, contact_id: uuid.UUID) -> uuid.UUID:
    return uuid.UUID(
        str(await su.fetchval("select id from leads where contact_id = $1", contact_id))
    )


async def _completed(order_id: uuid.UUID) -> None:
    payload: dict[str, Any] = {"order_id": str(order_id)}
    await on_order_completed(Event(1, TENANT_A, "order.completed", payload, 1, None))


async def test_a_sold_car_books_one_check_in_in_the_salespersons_language(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    """An export to Algeria, sold to sales1's customer: the check-in is
    sales1's, six weeks on at ten in the morning, and in Arabic because that
    is what sales1 reads."""
    await su.execute("update profiles set locale = 'ar' where id = $1", SALES_1)
    sold_at = datetime(2026, 11, 4, 18, 30, tzinfo=DUBAI)
    order_id = await _sold(
        su, sold_at, lead_id=await _lead_of(su, visibility_seed["s1"]), kind="export"
    )

    await _completed(order_id)
    await _completed(order_id)  # a retried event

    [task] = await su.fetch(
        "select assignee_id, title, due_at, contact_id, kind from tasks where source = 'rule'"
    )
    assert task["assignee_id"] == SALES_1
    assert task["contact_id"] == visibility_seed["s1"]
    assert task["kind"] == "follow_up"
    assert task["title"].startswith("متابعة ما بعد البيع")
    assert task["due_at"] == datetime(2026, 12, 16, 10, 0, tzinfo=DUBAI)


async def test_with_no_lead_the_check_in_is_whoever_made_the_order(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    order_id = await _sold(su, datetime(2026, 11, 4, 9, 0, tzinfo=DUBAI))
    await _completed(order_id)
    [task] = await su.fetch("select assignee_id, title, due_at from tasks where source = 'rule'")
    assert task["assignee_id"] == MANAGER
    assert task["title"] == (
        "After-sale check-in: how is the 2025 BYD Seal? Ask for a review or a referral."
    )
    assert task["due_at"] == datetime(2026, 11, 11, 10, 0, tzinfo=DUBAI), "a week, for a local sale"


async def test_a_past_buyer_is_seen_on_customer_360(
    db: None, su: asyncpg.Connection, visibility_seed: dict[str, uuid.UUID]
) -> None:
    contact = visibility_seed["s1"]
    await _sold(su, datetime(2026, 11, 4, 9, 0, tzinfo=DUBAI), lead_id=await _lead_of(su, contact))
    customer = await get_customer(_ctx(SALES_1, "sales"), contact)
    [bought] = customer["purchases"]
    assert bought["car"] == "2025 BYD Seal"
    assert bought["price"] == {"amount_minor": 210_000 * AED, "currency": "AED"}
    assert bought["purchase_type"] == "local"
