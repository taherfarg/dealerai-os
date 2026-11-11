"""What a car should be priced at, and proposing it when that changes.

The arithmetic is code on purpose. A price is the one number this product may
never get wrong, and a proposal a manager approves has to be explainable to the
dirham: landed cost, the dealer's target margin, the aging ladder, rounding.
A model would make the same figure differently on a second asking. Where the
intelligence is, is in what runs it — every morning, for every car, unprompted
— and in the demand signal the sales copilot already produces: a car customers
are asking about is not a car whose price is the problem.

Nothing here changes a price. It proposes, through the approvals queue, and the
price changes when somebody allowed to change prices says yes — on the same
path as the price endpoint, so history is written and published content that
quoted the old figure is caught.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import UUID

import asyncpg
import structlog
from pydantic import BaseModel, Field, model_validator

from ..core.money import Money, exponent
from ..events.bus import emit
from ..guards import price as price_guard
from ..orchestrator.approvals import request_approval

log = structlog.get_logger()

BPS = 10_000

Action = Literal[
    "set_price",  # no price yet: here is one
    "reduce",  # aged past a step of the ladder, and nobody is asking about it
    "hold",  # on target, or customers are asking — price is not the problem
    "below_floor",  # listed under the margin the dealer said it must keep
    "no_cost",  # nothing recorded for what it cost, so nothing to price from
    "other_currency",  # priced in one currency, costed in another
    "not_for_sale",  # sold, reserved, draft or archived
]

#: What leads a proposal to be made. The others are reported, never proposed.
PROPOSED: frozenset[str] = frozenset({"set_price", "reduce"})


class AgeStep(BaseModel):
    days: int = Field(ge=1, le=3650)
    cut_bps: int = Field(ge=1, le=5_000, description="Cut from the target, in basis points.")


class PricingRules(BaseModel):
    """A dealership's pricing rules as they arrive from a settings screen —
    shape checked, consistency not yet. See PricingSettings."""

    enabled: bool = True
    #: Gross margin on the list price the dealer aims for. 12%.
    target_margin_bps: int = Field(default=1_200, ge=0, le=9_000)
    #: The margin the floor keeps. A car is never proposed below it. 5%.
    floor_margin_bps: int = Field(default=500, ge=0, le=9_000)
    #: Prices end on a round number: AED 500 by default.
    round_to_major: int = Field(default=500, ge=1, le=100_000)
    steps: list[AgeStep] = Field(
        default_factory=lambda: [
            AgeStep(days=45, cut_bps=300),
            AgeStep(days=60, cut_bps=300),
            AgeStep(days=90, cut_bps=500),
        ],
        max_length=10,
    )
    #: Leads on a car in the last 30 days that mean "hold, people are asking".
    #: Zero turns the demand check off.
    hold_if_leads_30d: int = Field(default=3, ge=0, le=1_000)
    #: What the money tied up in a car costs a year, on its landed cost — the
    #: holding cost in lifecycle/numbers.py. 8%.
    holding_rate_bps: int = Field(default=800, ge=0, le=5_000)
    #: And what keeping it costs a day whatever it cost: storage, insurance.
    holding_per_day_major: int = Field(default=0, ge=0, le=100_000)


class PricingSettings(PricingRules):
    """A dealership's pricing rules. The defaults are a used-car norm, not
    advice: every one of them is the dealer's to change."""

    @model_validator(mode="after")
    def _floor_under_target(self) -> PricingSettings:
        if self.floor_margin_bps > self.target_margin_bps:
            raise ValueError("the floor's margin cannot be above the target margin")
        return self


@dataclass(frozen=True, slots=True)
class Facts:
    """Everything a recommendation is made from, read in one place."""

    status: str
    currency: str
    tenant_currency: str
    price_minor: int | None
    floor_minor: int | None
    landed_minor: int
    cost_lines: int
    days_in_stock: int
    leads_30d: int


@dataclass(frozen=True, slots=True)
class Recommendation:
    action: Action
    #: The list price proposed, when there is one to propose.
    price_minor: int | None
    #: A new floor, only when the current one is missing or under the margin.
    floor_minor: int | None
    #: What the price should be at this age, whether or not that is a change.
    ideal_minor: int | None
    target_minor: int | None
    currency: str
    #: Codes the screens and the summary turn into words: "aged:60",
    #: "no_leads", "demand:4", "on_target", "floor_missing", "floor_low".
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _round_up(minor: int, unit: int) -> int:
    return -(-minor // unit) * unit


def _round_down(minor: int, unit: int) -> int:
    return (minor // unit) * unit


def _price_for_margin(landed_minor: int, margin_bps: int) -> int:
    """The price at which (price - cost) / price is the margin. Exact integers:
    cost / (1 - m), rounded up so the margin is never a fraction short."""
    return -(-landed_minor * BPS // (BPS - margin_bps))


def recommend(facts: Facts, settings: PricingSettings) -> Recommendation:
    """Pure. Every rule in this module is in here, and testable without a database."""

    def nothing(action: Action, *reasons: str) -> Recommendation:
        return Recommendation(action, None, None, None, None, facts.currency, list(reasons))

    if facts.status != "available":
        return nothing("not_for_sale", f"status:{facts.status}")
    if facts.cost_lines == 0 or facts.landed_minor <= 0:
        return nothing("no_cost")
    if facts.currency != facts.tenant_currency:
        return nothing("other_currency")

    unit = settings.round_to_major * 10 ** exponent(facts.currency)
    target = _round_up(_price_for_margin(facts.landed_minor, settings.target_margin_bps), unit)
    floor = _round_up(_price_for_margin(facts.landed_minor, settings.floor_margin_bps), unit)

    # The ladder walks down from the target: each step a car has aged past cuts
    # the target by its share. Never below the floor, whatever the ladder says.
    ladder = target
    passed: list[str] = []
    for step in sorted(settings.steps, key=lambda s: s.days):
        if facts.days_in_stock >= step.days:
            ladder = ladder * (BPS - step.cut_bps) // BPS
            passed.append(f"aged:{step.days}")
    ideal = max(floor, _round_down(ladder, unit))

    reasons: list[str] = []
    new_floor: int | None = None
    if facts.floor_minor is None:
        new_floor, reasons = floor, ["floor_missing"]
    elif facts.floor_minor < floor:
        new_floor, reasons = floor, ["floor_low"]

    def made(action: Action, price: int | None, *more: str) -> Recommendation:
        return Recommendation(
            action, price, new_floor, ideal, target, facts.currency, [*more, *reasons]
        )

    if facts.price_minor is None:
        return made("set_price", ideal, *passed)
    if facts.price_minor < (facts.floor_minor if facts.floor_minor is not None else floor):
        return made("below_floor", None)
    if settings.hold_if_leads_30d and facts.leads_30d >= settings.hold_if_leads_30d:
        # Customers are asking. Cutting the price of a car people want is
        # giving away margin to solve a problem the car does not have.
        return made("hold", None, f"demand:{facts.leads_30d}")
    if not passed:
        # Only age moves a price down. A fresh car listed above the target is
        # the dealer leaving room to negotiate, and proposing to cut it on day
        # five would be the system second-guessing a decision it was not asked
        # about.
        above = facts.price_minor > target
        return made("hold", None, "above_target" if above else "on_target")
    if facts.price_minor > ideal:
        more = [*passed, "no_leads"] if facts.leads_30d == 0 else passed
        return made("reduce", ideal, *more)
    return made("hold", None, "on_target")


# --------------------------------------------------------------------------
# reading the facts
# --------------------------------------------------------------------------

_FACTS = """
select e.status, e.currency, t.currency as tenant_currency, e.price_minor,
       e.min_price_minor, e.landed_cost_minor, e.cost_lines, e.days_in_stock,
       (select count(*) from leads l
         where l.vehicle_id = e.vehicle_id
           and l.created_at > now() - interval '30 days')::int as leads_30d
  from v_vehicle_economics e
  join tenants t on t.id = e.tenant_id
 where e.vehicle_id = $1
"""


async def settings_for(conn: asyncpg.Connection, tenant_id: UUID) -> PricingSettings:
    raw = await conn.fetchval("select pricing_settings from tenants where id = $1", tenant_id)
    return PricingSettings.model_validate(raw or {})


async def facts_for(conn: asyncpg.Connection, vehicle_id: UUID) -> Facts | None:
    """The facts for one car — through the buy-side wall, so on a session that
    is not cleared for it the cost reads as nothing and the answer is no_cost."""
    row = await conn.fetchrow(_FACTS, vehicle_id)
    if row is None:
        return None
    return Facts(
        status=row["status"],
        currency=row["currency"],
        tenant_currency=row["tenant_currency"],
        price_minor=row["price_minor"],
        floor_minor=row["min_price_minor"],
        landed_minor=int(row["landed_cost_minor"]),
        cost_lines=int(row["cost_lines"]),
        days_in_stock=int(row["days_in_stock"]),
        leads_30d=int(row["leads_30d"]),
    )


# --------------------------------------------------------------------------
# proposing
# --------------------------------------------------------------------------

KIND = "price_change"


def _label(car: asyncpg.Record) -> str:
    return " ".join(
        str(p) for p in (car["model_year"], car["make"], car["model"], car["trim"]) if p
    )


async def propose(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    vehicle_id: UUID,
    recommendation: Recommendation,
    *,
    facts: Facts,
) -> UUID | None:
    """Put a recommendation in the approvals queue, unless one is waiting already.

    One open proposal per car. A second while the first is unanswered is the
    queue nagging, and a person who sees two proposals for one car decides
    neither.
    """
    if recommendation.action not in PROPOSED or recommendation.price_minor is None:
        return None
    waiting = await conn.fetchval(
        """select 1 from approvals
            where entity_id = $1 and kind = $2 and status = 'pending'""",
        vehicle_id,
        KIND,
    )
    if waiting:
        return None

    car = await conn.fetchrow(
        "select make, model, model_year, trim from vehicles where id = $1", vehicle_id
    )
    if car is None:
        return None
    after = Money(recommendation.price_minor, recommendation.currency).display()
    before = (
        Money(facts.price_minor, recommendation.currency).display()
        if facts.price_minor is not None
        else "—"
    )
    # Numbers and the car's name: the same summary reads in either language.
    summary = f"{_label(car)} · {before} → {after}"
    return await request_approval(
        conn,
        tenant_id=tenant_id,
        kind=KIND,
        summary=summary,
        payload={
            "vehicle_id": str(vehicle_id),
            "before_minor": facts.price_minor,
            "after_minor": recommendation.price_minor,
            "floor_minor": recommendation.floor_minor,
            "currency": recommendation.currency,
            "reasons": recommendation.reasons,
            "days_in_stock": facts.days_in_stock,
            "leads_30d": facts.leads_30d,
        },
        entity_type="vehicle",
        entity_id=vehicle_id,
    )


async def sweep(conn: asyncpg.Connection, tenant_id: UUID) -> dict[str, int]:
    """Every available car, once: recommend, and propose what should move.

    Runs on the worker's session, which has no person and so sees the buy side
    — the same as every other job that acts on rows already authorised.
    """
    settings = await settings_for(conn, tenant_id)
    counts = {"cars": 0, "proposed": 0}
    if not settings.enabled:
        return counts
    for row in await conn.fetch(
        "select id from vehicles where tenant_id = $1 and status = 'available'", tenant_id
    ):
        counts["cars"] += 1
        facts = await facts_for(conn, row["id"])
        if facts is None:
            continue
        recommendation = recommend(facts, settings)
        if await propose(conn, tenant_id, row["id"], recommendation, facts=facts):
            counts["proposed"] += 1
    return counts


# --------------------------------------------------------------------------
# applying — the one path a price changes on
# --------------------------------------------------------------------------


class PriceMoved(Exception):
    """The price is no longer what the proposal was made against."""


async def set_price(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    vehicle_id: UUID,
    amount_minor: int,
    reason: str,
    actor_id: str,
    floor_minor: int | None = None,
    expect_minor: int | None | Literal["any"] = "any",
) -> asyncpg.Record | None:
    """Change a list price: history, and the event that tells everything else.

    The price endpoint and an approved proposal both come here, so neither can
    forget the history row or the event — and a proposal approved after
    somebody changed the price by hand is refused rather than applied over
    them (`expect_minor`). Returns None when there is no such car.
    """
    current = await conn.fetchrow(
        "select price_minor, currency from vehicles where id = $1 for update", vehicle_id
    )
    if current is None:
        return None
    if expect_minor != "any" and current["price_minor"] != expect_minor:
        raise PriceMoved(
            f"the price is {current['price_minor']}, not the {expect_minor} it was proposed against"
        )

    if floor_minor is not None:
        await conn.execute(
            "update vehicles set min_price_minor = $2 where id = $1", vehicle_id, floor_minor
        )
    row = await conn.fetchrow(
        "update vehicles set price_minor = $2 where id = $1 returning *", vehicle_id, amount_minor
    )
    await conn.execute(
        """insert into vehicle_price_history
               (tenant_id, vehicle_id, price_minor, currency, reason, actor_type, actor_id)
           values ($1,$2,$3,$4,$5,'user',$6)""",
        tenant_id,
        vehicle_id,
        amount_minor,
        current["currency"],
        reason,
        actor_id,
    )
    if current["price_minor"] != amount_minor:
        await emit(
            conn,
            "vehicle.price_changed",
            {
                "vehicle_id": str(vehicle_id),
                "before_minor": current["price_minor"],
                "after_minor": amount_minor,
                "currency": current["currency"],
            },
            tenant_id=tenant_id,
            priority=5,
        )
    return row


async def apply_decision(conn: asyncpg.Connection, tenant_id: UUID, approval_id: UUID) -> str:
    """An approved price proposal, applied. Returns what happened, for the log."""
    approval = await conn.fetchrow(
        "select status, payload, decided_by from approvals where id = $1 and kind = $2",
        approval_id,
        KIND,
    )
    if approval is None or approval["status"] != "approved":
        return "not approved"
    payload = approval["payload"] or {}
    try:
        await set_price(
            conn,
            tenant_id=tenant_id,
            vehicle_id=UUID(str(payload["vehicle_id"])),
            amount_minor=int(payload["after_minor"]),
            floor_minor=payload.get("floor_minor"),
            reason="pricing proposal approved: " + ", ".join(payload.get("reasons") or []),
            actor_id=str(approval["decided_by"]),
            expect_minor=payload.get("before_minor"),
        )
    except PriceMoved as exc:
        # Somebody changed the price by hand after the proposal was made. Their
        # decision is newer than this one; tomorrow's sweep proposes afresh.
        log.warning("price_proposal_stale", approval_id=str(approval_id), error=str(exc))
        return "stale"
    return "applied"


# --------------------------------------------------------------------------
# content that quotes a price that is no longer the price
# --------------------------------------------------------------------------

#: Content that has not reached the public yet, and can still be stopped.
UNPUBLISHED = ("draft", "rendering", "pending_approval", "approved", "scheduled")


async def stale_content(
    conn: asyncpg.Connection,
    vehicle_id: UUID,
    *,
    price_minor: int,
    currency: str,
) -> dict[str, list[UUID]]:
    """Stop unpublished pieces that quote a figure that is not the new price,
    and list the published ones that do.

    "Quotes another figure" is the price guard's question exactly, so the price
    guard answers it: a caption that names anything but the current price is a
    caption that would publish a wrong one.
    """
    allowed = {Money(price_minor, currency).major}
    stopped: list[UUID] = []
    published: list[UUID] = []
    rows = await conn.fetch(
        """select c.id, c.status,
                  string_agg(concat_ws(' ', p.hook, p.caption, p.cta), ' ') as text
             from content_items c
             join content_copy p on p.content_item_id = c.id
            where c.vehicle_id = $1
              and c.status = any($2::text[] || array['published'])
            group by c.id""",
        vehicle_id,
        list(UNPUBLISHED),
    )
    for row in rows:
        if not price_guard.check(row["text"] or "", allowed=allowed):
            continue
        if row["status"] == "published":
            published.append(row["id"])
            continue
        await conn.execute(
            """update content_items set status = 'rejected', rejection_reason = $2
                where id = $1""",
            row["id"],
            f"the price changed to {Money(price_minor, currency)}; this quotes another figure",
        )
        stopped.append(row["id"])
    return {"stopped": stopped, "published": published}
