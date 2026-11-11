"""Lifecycle L8: what the month made, and what the stock costs to keep.

docs/lifecycle/README.md § L8. Arithmetic on rows L1–L7 already write, in
integer minor units of the dealer's currency. Everything here is the buy side:
the caller's session must be cleared for it (`buy_side=True`), or the costs
read as nothing and every car looks free to keep.

One module for the dashboard and the brief, because a number shown in two
places is a number that can disagree with itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from ..core.money import Money, exponent
from .pricing import BPS, PricingSettings

DAYS_A_YEAR = 365
#: How many of the costliest cars the dashboard and the brief name.
COSTLY_SHOWN = 5
#: When the dealer's pricing ladder has no steps, the age a car counts as old.
OLD_AFTER_DAYS = 45


def holding_minor(landed_minor: int, days: int, *, rate_bps: int, per_day_minor: int) -> int:
    """What keeping a car for `days` cost: the money tied up in it at the
    yearly rate, plus the daily amount. Rounded up, so it never reads lower
    than it is."""
    if days <= 0:
        return 0
    tied_up = -(-landed_minor * rate_bps * days // (BPS * DAYS_A_YEAR))
    return tied_up + per_day_minor * days


def old_after(settings: PricingSettings) -> int:
    """The dealer already said when a car is old: the first step of its ladder."""
    return min((step.days for step in settings.steps), default=OLD_AFTER_DAYS)


@dataclass(frozen=True, slots=True)
class Month:
    sold: int
    #: The vehicle price of every car sold — fees, freight and duties are the buyer's.
    revenue_minor: int
    #: Price less landed cost, over the sold cars that have a cost recorded.
    gross_minor: int
    costed: int
    #: Null before a car is sold this month.
    avg_days_held: int | None

    @property
    def gross_per_car_minor(self) -> int | None:
        return self.gross_minor // self.costed if self.costed else None


@dataclass(frozen=True, slots=True)
class Costly:
    vehicle_id: UUID
    label: str
    days_held: int
    holding_minor: int
    #: The margin at list once holding is paid; null without a price in the dealer's currency.
    margin_left_minor: int | None


@dataclass(frozen=True, slots=True)
class Business:
    currency: str
    month: Month
    in_stock: int
    tied_up_minor: int
    holding_per_day_minor: int
    old_after_days: int
    costly: list[Costly] = field(default_factory=list)


_SOLD = """
select ch.amount_minor as price_minor, e.landed_cost_minor, e.cost_lines, e.days_held
  from sale_orders o
  join sale_charges ch on ch.order_id = o.id and ch.kind = 'vehicle'
  join v_vehicle_economics e on e.vehicle_id = o.vehicle_id
 where o.tenant_id = $1 and o.status = 'completed' and o.currency = $4
   and o.completed_at >= $2 and o.completed_at < $3
"""

_STOCK = """
select e.vehicle_id, e.currency, e.price_minor, e.landed_cost_minor, e.cost_lines, e.days_held,
       v.model_year, v.make, v.model, v.trim
  from v_vehicle_economics e
  join vehicles v on v.id = e.vehicle_id
 where e.tenant_id = $1 and e.status in ('draft', 'available', 'reserved')
"""


def label(car: Any) -> str:
    parts = (car["model_year"], car["make"], car["model"], car["trim"])
    return " ".join(str(part) for part in parts if part)


def month_of(rows: list[Any]) -> Month:
    costed = [r for r in rows if r["cost_lines"]]
    return Month(
        sold=len(rows),
        revenue_minor=sum(int(r["price_minor"]) for r in rows),
        gross_minor=sum(int(r["price_minor"]) - int(r["landed_cost_minor"]) for r in costed),
        costed=len(costed),
        avg_days_held=round(sum(int(r["days_held"]) for r in rows) / len(rows)) if rows else None,
    )


def stock_of(
    rows: list[Any], *, currency: str, settings: PricingSettings
) -> tuple[int, int, int, list[Costly]]:
    """How many cars, the money in them, what they cost a day, and the costliest old ones."""
    per_day = settings.holding_per_day_major * 10 ** exponent(currency)

    def held(landed: int, days: int) -> int:
        return holding_minor(
            landed, days, rate_bps=settings.holding_rate_bps, per_day_minor=per_day
        )

    # Every car, costed or not: storage and insurance are paid on a car whose
    # invoice nobody has entered yet. Its money tied up reads as nothing until
    # they do, and it has no margin to speak of.
    threshold = old_after(settings)
    costly = []
    for r in rows:
        days = int(r["days_held"])
        landed = int(r["landed_cost_minor"])
        holding = held(landed, days)
        if days <= threshold or holding == 0:
            continue
        priced = r["cost_lines"] and r["price_minor"] is not None and r["currency"] == currency
        costly.append(
            Costly(
                vehicle_id=r["vehicle_id"],
                label=label(r),
                days_held=days,
                holding_minor=holding,
                margin_left_minor=int(r["price_minor"]) - landed - holding if priced else None,
            )
        )
    costly.sort(key=lambda c: (-c.holding_minor, -c.days_held))
    return (
        len(rows),
        sum(int(r["landed_cost_minor"]) for r in rows),
        sum(held(int(r["landed_cost_minor"]), 1) for r in rows),
        costly[:COSTLY_SHOWN],
    )


async def business(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    since: datetime,
    until: datetime,
    settings: PricingSettings,
) -> Business:
    """The month from `since` to `until`, and the stock as it is now."""
    currency = str(await conn.fetchval("select currency from tenants where id = $1", tenant_id))
    sold = await conn.fetch(_SOLD, tenant_id, since, until, currency)
    stock = await conn.fetch(_STOCK, tenant_id)
    in_stock, tied_up, per_day, costly = stock_of(stock, currency=currency, settings=settings)
    return Business(
        currency=currency,
        month=month_of(sold),
        in_stock=in_stock,
        tied_up_minor=tied_up,
        holding_per_day_minor=per_day,
        old_after_days=old_after(settings),
        costly=costly,
    )


def render(numbers: Business) -> str:
    """For the brief's facts block — every figure in the form the headline may
    use it, because guards/facts.py holds the headline to exactly these."""

    def money(minor: int) -> str:
        return Money(minor, numbers.currency).display()

    month = numbers.month
    lines = ["", "## This month, to yesterday"]
    if month.sold:
        sold = f"- cars sold: {month.sold}; their price: {money(month.revenue_minor)}"
        if month.costed:
            sold += f"; gross: {money(month.gross_minor)}"
            if month.costed < month.sold:
                sold += f" (on the {month.costed} with a cost recorded)"
            sold += f"; gross per car: {money(month.gross_per_car_minor or 0)}"
        lines += [sold, f"- days held, on average, by the cars sold: {month.avg_days_held}"]
    else:
        lines.append("- no car sold yet")
    lines += [
        "",
        "## The stock",
        f"- cars in stock: {numbers.in_stock}; money tied up in them: "
        f"{money(numbers.tied_up_minor)}; keeping them costs {money(numbers.holding_per_day_minor)}"
        " a day",
    ]
    if numbers.costly:
        lines += ["", f"## Costing money to keep (held over {numbers.old_after_days} days)"]
        for car in numbers.costly:
            line = f"- {car.label}: {car.days_held} days, {money(car.holding_minor)} to keep so far"
            if car.margin_left_minor is not None:
                line += f"; margin left at list: {money(car.margin_left_minor)}"
            lines.append(line)
    return "\n".join(lines)
