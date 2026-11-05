"""Lifecycle L5: what customers asked for, what such a car is worth to this
dealer, and the most to pay for one.

docs/lifecycle/README.md § L5. The model does one thing here: it reads a
customer's words into the cars they name. Everything after that — whether the
dealer has one, what its own history says one sells for, the bid — is code, in
integer minor units of the dealer's currency. The history is the buy side: the
caller's session must be cleared for it, or every car reads as never sold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg
import structlog
from pydantic import BaseModel, Field

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..ai.prompts import load
from ..core.money import exponent
from . import numbers, recon
from .pricing import BPS, PricingSettings

log = structlog.get_logger()

#: The demand the buying list counts: what customers asked for in the last 30 days.
WANT_DAYS = 30
#: The sales the valuation reads: the last year of them.
HISTORY_DAYS = 365
#: A car the dealer has, or has on its way. A car held for a buyer is not stock.
HAD = ("draft", "available")
#: Where L3 records reconditioning in the ledger. Not part of what a car costs
#: to land: an appraisal brings the repairs of the car in front of it.
RECON = tuple(sorted({*recon.CATEGORY.values(), "repair"}))
#: Cars one interest may name. "Land Cruiser or Patrol" is two; ten is a list, not a want.
MAX_CARS = 3

# --------------------------------------------------------------------------
# reading what a customer asked for
# --------------------------------------------------------------------------


class Car(BaseModel):
    make: str = Field(max_length=60)
    model: str = Field(max_length=80)
    model_year: int | None = None
    quoted: str = Field(
        max_length=200, description="The customer's words that name this car, copied exactly."
    )


class Read(BaseModel):
    cars: list[Car] = Field(default_factory=list, max_length=10)


def verify(read: Read, interest: str) -> list[Car]:
    """Keep the cars the model can point at in the customer's words, once each.

    Whether "لاند كروزر" is a Toyota Land Cruiser is the model's call; that the
    words it says name the car are in the interest is code's. A car it cannot
    point at is one it made up.
    """
    words = interest.casefold()
    kept: list[Car] = []
    seen: set[tuple[str, str]] = set()
    for car in read.cars:
        make, model, quoted = car.make.strip(), car.model.strip(), car.quoted.strip()
        if not (make and model and quoted) or quoted.casefold() not in words:
            continue
        key = (make.casefold(), model.casefold())
        if key in seen:
            continue
        seen.add(key)
        year = car.model_year if car.model_year and 1950 <= car.model_year <= 2100 else None
        kept.append(Car(make=make, model=model, model_year=year, quoted=quoted))
    return kept[:MAX_CARS]


async def read_interest(
    *, tenant_id: UUID, interest: str, catalogue: list[tuple[str, str]]
) -> list[Car]:
    """One call: the cars the words name, spelled as the dealer spells them."""
    listed = "\n".join(f"- {make} / {model}" for make, model in catalogue) or "nothing yet"
    result = await complete(
        TaskKind.ENRICHMENT,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("wants")),
        messages=(
            f"## The dealer's catalogue\n{listed}\n\n"
            f"## What the customer wants\n<untrusted>\n{interest}\n</untrusted>"
        ),
        output_schema=Read,
        trace_name="wants",
    )
    read = result.parsed if isinstance(result.parsed, Read) else Read()
    cars = verify(read, interest)
    log.info("wants_read", read=len(read.cars), kept=len(cars), cost_usd=round(result.cost_usd, 6))
    return cars


_INTEREST = """
select c.profile -> 'interest' ->> 'value' as interest,
       c.profile -> 'interest' ->> 'updated_at' as asked_at,
       (select w.interest from customer_wants w where w.contact_id = c.id limit 1) as read
  from contacts c where c.id = $1
"""


async def remember(conn: asyncpg.Connection, contact_id: UUID) -> str | None:
    """What a customer's interest says now, or None when nothing needs reading.

    No interest any more clears what was read from the old one."""
    row = await conn.fetchrow(_INTEREST, contact_id)
    if row is None or not row["interest"]:
        await conn.execute("delete from customer_wants where contact_id = $1", contact_id)
        return None
    return None if row["read"] == row["interest"] else str(row["interest"])


async def catalogue(conn: asyncpg.Connection, tenant_id: UUID) -> list[tuple[str, str]]:
    """How this dealer spells its cars: every one it has stocked, and every one
    a customer already asked for — so a second ask for a car it has never had
    is spelled, and grouped, as the first was."""
    rows = await conn.fetch(
        """select make, model from vehicles
            where tenant_id = $1 and make is not null and model is not null
           union
           select make, model from customer_wants
            where tenant_id = $1 and make is not null
           order by 1, 2 limit 300""",
        tenant_id,
    )
    return [(r["make"], r["model"]) for r in rows]


async def store(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    contact_id: UUID,
    *,
    interest: str,
    cars: list[Car],
) -> bool:
    """Write what was read — if the interest still says what was read. False
    when it changed meanwhile, and the caller reads it again."""
    row = await conn.fetchrow(
        """select profile -> 'interest' ->> 'value' as interest,
                  profile -> 'interest' ->> 'updated_at' as asked_at
             from contacts where id = $1 for update""",
        contact_id,
    )
    if row is None or row["interest"] != interest:
        return False
    asked_at = datetime.fromisoformat(row["asked_at"]) if row["asked_at"] else None
    await conn.execute("delete from customer_wants where contact_id = $1", contact_id)
    named: list[Car | None] = list(cars) or [None]
    for car in named:
        await conn.execute(
            """insert into customer_wants (tenant_id, contact_id, interest, make, model,
                                           model_year, quoted, asked_at)
               values ($1, $2, $3, $4, $5, $6, $7, coalesce($8, now()))""",
            tenant_id,
            contact_id,
            interest,
            car.make if car else None,
            car.model if car else None,
            car.model_year if car else None,
            car.quoted if car else None,
            asked_at,
        )
    return True


# --------------------------------------------------------------------------
# what such a car is worth, from the dealer's own sales
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Worth:
    """The dealer's own sales of a make and model in the last year. Medians, so
    one odd deal does not move it; the costs only over the cars that have one."""

    sold: int = 0
    price_minor: int | None = None
    landed_minor: int | None = None
    #: What landing one cost on top of its purchase: freight, customs, fees.
    on_top_minor: int | None = None
    days_to_sell: int | None = None


def same_car(car: str, make: str, model: str) -> str:
    """SQL: the stock car aliased `car` is the make and model given, case aside —
    or that model with a trim after it, either way round. A dealer lists a
    "Land Cruiser 4.0"; a customer asks for a "Land Cruiser".
    ponytail: a prefix of whole words, so "Seal" is also "Seal U"; a table of
    models per make if that ever lists the wrong car."""
    return (
        f"lower({car}.make) = lower({make}) and (lower({car}.model) = lower({model})"
        f" or starts_with(lower({car}.model), lower({model}) || ' ')"
        f" or starts_with(lower({model}), lower({car}.model) || ' '))"
    )


_HISTORY = f"""
select count(*) as sold,
       percentile_disc(0.5) within group (order by ch.amount_minor) as price_minor,
       percentile_disc(0.5) within group (order by e.landed_cost_minor)
         filter (where e.cost_lines > 0) as landed_minor,
       percentile_disc(0.5) within group
         (order by e.landed_cost_minor - p.purchase_minor - p.recon_minor)
         filter (where p.purchase_minor > 0) as on_top_minor,
       percentile_disc(0.5) within group (order by e.days_held) as days_to_sell
  from sale_orders o
  join sale_charges ch on ch.order_id = o.id and ch.kind = 'vehicle'
  join vehicles v on v.id = o.vehicle_id
  join v_vehicle_economics e on e.vehicle_id = o.vehicle_id
  cross join lateral (
    select coalesce(sum(amount_tenant_minor) filter (where category = 'purchase'), 0)
             as purchase_minor,
           coalesce(sum(amount_tenant_minor) filter (where category = any($6::text[])), 0)
             as recon_minor
      from vehicle_costs where vehicle_id = o.vehicle_id
  ) p
 where o.tenant_id = $1 and o.status = 'completed' and o.currency = $2
   and o.completed_at > now() - make_interval(days => $3)
   and {same_car("v", "$4", "$5")}
"""


def key(make: str, model: str) -> tuple[str, str]:
    return (make.strip().casefold(), model.strip().casefold())


async def worth(
    conn: asyncpg.Connection, tenant_id: UUID, currency: str, make: str, model: str
) -> Worth:
    """The dealer's sales of this car in the last year.
    ponytail: make and model, not the year — a dealer's own history is a few
    sales per model; split by year once there are enough to split."""
    r = await conn.fetchrow(
        _HISTORY, tenant_id, currency, HISTORY_DAYS, make.strip(), model.strip(), list(RECON)
    )
    if r is None or not r["sold"]:
        return Worth()
    return Worth(
        sold=int(r["sold"]),
        price_minor=_int(r["price_minor"]),
        landed_minor=_int(r["landed_minor"]),
        on_top_minor=_int(r["on_top_minor"]),
        days_to_sell=_int(r["days_to_sell"]),
    )


def _int(value: Any) -> int | None:
    return None if value is None else int(value)


# --------------------------------------------------------------------------
# the most to pay
# --------------------------------------------------------------------------

Source = Literal["history", "typed", "assumed"]


@dataclass(frozen=True, slots=True)
class Bid:
    """The most to pay for a car, line by line, from the price it should sell at down."""

    expected_price_minor: int
    price_from: Source
    #: The target margin kept on that price.
    margin_minor: int
    on_top_minor: int
    on_top_from: Source
    holding_minor: int
    days_to_sell: int
    days_from: Source
    repairs_minor: int
    #: Zero when the costs eat the whole price: such a car is not worth buying at all.
    max_bid_minor: int


def max_bid(
    expected_price_minor: int,
    *,
    currency: str,
    settings: PricingSettings,
    on_top_minor: int,
    days_to_sell: int,
    repairs_minor: int = 0,
    price_from: Source = "history",
    on_top_from: Source = "history",
    days_from: Source = "history",
) -> Bid:
    """Pure. The landed cost that keeps the target margin at the expected
    price, less what landing it costs on top of the purchase, the repairs and
    holding it until it sells — rounded down to the dealer's rounding unit, so
    a bid never pays more than the rule.

    Holding is counted on the most the car may land at, not on what it will:
    a bid that over-counts holding is a little low, never a little high."""
    max_landed = expected_price_minor * (BPS - settings.target_margin_bps) // BPS
    holding = numbers.holding_minor(
        max_landed,
        days_to_sell,
        rate_bps=settings.holding_rate_bps,
        per_day_minor=settings.holding_per_day_major * 10 ** exponent(currency),
    )
    unit = settings.round_to_major * 10 ** exponent(currency)
    left = max_landed - on_top_minor - repairs_minor - holding
    return Bid(
        expected_price_minor=expected_price_minor,
        price_from=price_from,
        margin_minor=expected_price_minor - max_landed,
        on_top_minor=on_top_minor,
        on_top_from=on_top_from,
        holding_minor=holding,
        days_to_sell=days_to_sell,
        days_from=days_from,
        repairs_minor=repairs_minor,
        max_bid_minor=max(left // unit * unit, 0),
    )


def bid_from(
    worth: Worth,
    *,
    currency: str,
    settings: PricingSettings,
    expected_price_minor: int | None = None,
    on_top_minor: int | None = None,
    repairs_minor: int = 0,
) -> Bid | None:
    """The bid from history, with whatever a person typed winning over it.
    None when nothing says what the car sells for."""
    price = expected_price_minor if expected_price_minor is not None else worth.price_minor
    if price is None:
        return None
    on_top = on_top_minor if on_top_minor is not None else worth.on_top_minor
    days = worth.days_to_sell
    return max_bid(
        price,
        currency=currency,
        settings=settings,
        on_top_minor=on_top or 0,
        days_to_sell=days if days is not None else numbers.old_after(settings),
        repairs_minor=repairs_minor,
        price_from="typed" if expected_price_minor is not None else "history",
        on_top_from=(
            "typed"
            if on_top_minor is not None
            else "history"
            if worth.on_top_minor is not None
            else "assumed"
        ),
        days_from="history" if days is not None else "assumed",
    )


# --------------------------------------------------------------------------
# the buying list
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Asker:
    contact_id: UUID
    name: str | None
    model_year: int | None
    quoted: str
    budget_minor: int | None
    budget_currency: str | None
    destination: str | None
    asked_at: datetime


@dataclass(frozen=True, slots=True)
class Wanted:
    make: str
    model: str
    askers: list[Asker]
    worth: Worth
    bid: Bid | None

    @property
    def gross_minor(self) -> int | None:
        """What history says one of these makes, before holding."""
        w = self.worth
        return (
            None
            if w.price_minor is None or w.landed_minor is None
            else (w.price_minor - w.landed_minor)
        )


@dataclass(frozen=True, slots=True)
class BuyingList:
    currency: str
    since: datetime
    cars: list[Wanted] = field(default_factory=list)


_ASKED = f"""
select w.contact_id, w.make, w.model, w.model_year, w.quoted, w.asked_at, c.full_name,
       c.profile -> 'budget' -> 'value' as budget,
       c.profile -> 'destination' ->> 'value' as destination
  from customer_wants w
  join contacts c on c.id = w.contact_id
 where w.tenant_id = $1 and w.make is not null and w.asked_at >= $2
   and not exists (
     select 1 from vehicles v
      where v.tenant_id = w.tenant_id and v.status = any($3::text[])
        and {same_car("v", "w.make", "w.model")})
 order by w.asked_at desc
"""


def group(rows: list[Any]) -> dict[tuple[str, str], tuple[str, str, list[Asker]]]:
    """By make and model, case aside; spelled as the newest ask spells it. A
    customer who named the same car twice is one customer asking."""
    groups: dict[tuple[str, str], tuple[str, str, list[Asker]]] = {}
    for r in rows:
        named = key(r["make"], r["model"])
        make, model, askers = groups.setdefault(named, (r["make"], r["model"], []))
        if any(a.contact_id == r["contact_id"] for a in askers):
            continue
        budget = r["budget"] if isinstance(r["budget"], dict) else None
        askers.append(
            Asker(
                contact_id=r["contact_id"],
                name=r["full_name"],
                model_year=r["model_year"],
                quoted=r["quoted"],
                budget_minor=_int(budget.get("amount_minor")) if budget else None,
                budget_currency=budget.get("currency") if budget else None,
                destination=r["destination"],
                asked_at=r["asked_at"],
            )
        )
    return groups


async def buying_list(
    conn: asyncpg.Connection, tenant_id: UUID, *, since: datetime, settings: PricingSettings
) -> BuyingList:
    currency = str(await conn.fetchval("select currency from tenants where id = $1", tenant_id))
    rows = await conn.fetch(_ASKED, tenant_id, since, list(HAD))
    cars = []
    # ponytail: one history query per car asked for — a few dozen at most.
    for make, model, askers in group(rows).values():
        sold = await worth(conn, tenant_id, currency, make, model)
        cars.append(
            Wanted(
                make=make,
                model=model,
                askers=askers,
                worth=sold,
                bid=bid_from(sold, currency=currency, settings=settings),
            )
        )
    cars.sort(key=lambda w: (-len(w.askers), -(w.gross_minor or 0), w.make, w.model))
    return BuyingList(currency=currency, since=since, cars=cars)
