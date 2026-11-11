"""The deal desk: an order for a car, the invoice it is priced on, the payments
that reserve and then sell it.

Pollux's buyers are mostly abroad and pay in stages (docs/lifecycle/pollux.md):
a deposit to reserve the car, the balance once it is inspected and its papers
are ready, and the freight and duties as it ships. The invoice says each of
those separately. The slice's exit criterion: **an offer below the floor cannot
be sent; a deposit reserves the car and stops its marketing.**

* **The floor.** An order priced under the car's floor is not cleared until an
  owner or admin approves that exact price. Until then nothing can be taken
  against it — no deposit, no reservation.
* **The deposit.** When the deposit stage is paid in full, the order reserves
  the car: Postgres allows one reservation per car, the car's status changes,
  and its marketing stops.
* **Sold** is when every line of the invoice is paid.

Where the AI is: reading a transfer receipt — the SWIFT copy or bank slip a
buyer abroad sends on WhatsApp — into a proposed payment. Amounts as printed,
each found in the line it was read from, and no exchange rate unless the
receipt prints one. A person records it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

import asyncpg
import structlog
from google.genai import types
from pydantic import BaseModel, Field

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..ai.prompts import load
from ..core.errors import Conflict
from ..core.money import Money
from ..core.text import parse_number
from ..events.bus import emit
from ..orchestrator.approvals import request_approval
from .invoices import numbers_in

log = structlog.get_logger()

KIND = "price_below_floor"

Stage = Literal["deposit", "balance", "logistics"]
STAGES: tuple[Stage, ...] = ("deposit", "balance", "logistics")

#: Which stage pays for which lines of the invoice. The deposit is part of the
#: price; the balance is the rest of the price and fees; logistics is what it
#: costs to get the car to the buyer.
LOGISTICS = frozenset({"freight", "duties"})


# --------------------------------------------------------------------------
# the schedule — pure
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Line:
    kind: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class Schedule:
    """What each stage owes and has been paid, in the dealer's currency."""

    due: dict[str, int]
    paid: dict[str, int]
    total_minor: int

    @property
    def paid_minor(self) -> int:
        return sum(self.paid.values())

    @property
    def outstanding_minor(self) -> int:
        return self.total_minor - self.paid_minor

    def left(self, stage: str) -> int:
        return max(self.due[stage] - self.paid[stage], 0)

    @property
    def next_stage(self) -> str | None:
        return next((stage for stage in STAGES if self.left(stage) > 0), None)


def schedule(lines: list[Line], deposit_minor: int, paid: dict[str, int]) -> Schedule:
    """Split an invoice into the three stages a buyer pays it in."""
    logistics = sum(line.amount_minor for line in lines if line.kind in LOGISTICS)
    price_and_fees = sum(line.amount_minor for line in lines if line.kind not in LOGISTICS)
    if deposit_minor > price_and_fees:
        raise ValueError("the deposit is more than the price")
    return Schedule(
        due={
            "deposit": deposit_minor,
            "balance": price_and_fees - deposit_minor,
            "logistics": logistics,
        },
        paid={stage: paid.get(stage, 0) for stage in STAGES},
        total_minor=price_and_fees + logistics,
    )


def cleared(price_minor: int, floor_minor: int | None, approved_minor: int | None) -> bool:
    """May anything be taken against this price? At or over the floor, yes; under
    it, only at the exact price an owner or admin approved. No floor set is
    nothing to be under."""
    if floor_minor is None or price_minor >= floor_minor:
        return True
    return approved_minor == price_minor


# --------------------------------------------------------------------------
# reading an order
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Order:
    row: asyncpg.Record
    lines: list[asyncpg.Record]
    payments: list[asyncpg.Record]
    floor_minor: int | None
    vehicle_status: str

    @property
    def price_minor(self) -> int:
        return next(int(r["amount_minor"]) for r in self.lines if r["kind"] == "vehicle")

    @property
    def cleared(self) -> bool:
        return cleared(self.price_minor, self.floor_minor, self.row["approved_price_minor"])

    @property
    def schedule(self) -> Schedule:
        paid: dict[str, int] = {}
        for payment in self.payments:
            paid[payment["stage"]] = paid.get(payment["stage"], 0) + payment["amount_tenant_minor"]
        return schedule(
            [Line(r["kind"], int(r["amount_minor"])) for r in self.lines],
            int(self.row["deposit_minor"]),
            paid,
        )


async def load_order(
    conn: asyncpg.Connection, order_id: UUID, *, lock: bool = False
) -> Order | None:
    row = await conn.fetchrow(
        "select * from sale_orders where id = $1" + (" for update" if lock else ""), order_id
    )
    if row is None:
        return None
    car = await conn.fetchrow(
        "select min_price_minor, status from vehicles where id = $1", row["vehicle_id"]
    )
    return Order(
        row=row,
        lines=await conn.fetch(
            "select * from sale_charges where order_id = $1 order by position", order_id
        ),
        payments=await conn.fetch(
            "select * from sale_payments where order_id = $1 order by received_on, created_at",
            order_id,
        ),
        floor_minor=car["min_price_minor"] if car else None,
        vehicle_status=car["status"] if car else "archived",
    )


# --------------------------------------------------------------------------
# pricing an order
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Charge:
    kind: str
    description: str | None
    amount_minor: int


async def write_charges(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    order_id: UUID,
    price_minor: int,
    charges: list[Charge],
) -> None:
    """The invoice, replaced whole: the car's price first, then everything else."""
    await conn.execute("delete from sale_charges where order_id = $1", order_id)
    for position, charge in enumerate([Charge("vehicle", None, price_minor), *charges]):
        await conn.execute(
            """insert into sale_charges
                 (tenant_id, order_id, kind, description, amount_minor, position)
               values ($1, $2, $3, $4, $5, $6)""",
            tenant_id,
            order_id,
            charge.kind,
            charge.description,
            charge.amount_minor,
            position,
        )


async def ask_if_under_floor(
    conn: asyncpg.Connection, tenant_id: UUID, order: Order, *, currency: str
) -> UUID | None:
    """An order under the floor asks an owner or admin, once per price."""
    if order.cleared or order.floor_minor is None:
        return None
    pending = order.row["approval_id"]
    if pending is not None:
        waiting = await conn.fetchrow(
            "select status, payload from approvals where id = $1", pending
        )
        if (
            waiting is not None
            and waiting["status"] == "pending"
            and (waiting["payload"] or {}).get("price_minor") == order.price_minor
        ):
            return UUID(str(pending))
        await conn.execute(
            """update approvals set status = 'rejected', decided_at = now(),
                      decision_note = 'superseded by a new price'
                where id = $1 and status = 'pending'""",
            pending,
        )
    car = await conn.fetchrow(
        "select make, model, model_year from vehicles where id = $1", order.row["vehicle_id"]
    )
    label = " ".join(str(p) for p in (car["model_year"], car["make"], car["model"]) if p)
    price = Money(order.price_minor, currency).display()
    floor = Money(order.floor_minor, currency).display()
    approval_id = await request_approval(
        conn,
        tenant_id=tenant_id,
        kind=KIND,
        summary=f"{label} · {order.row['buyer_name']} · {price} · floor {floor}",
        payload={
            "order_id": str(order.row["id"]),
            "vehicle_id": str(order.row["vehicle_id"]),
            "price_minor": order.price_minor,
            "floor_minor": order.floor_minor,
            "currency": currency,
        },
        entity_type="vehicle",
        entity_id=order.row["vehicle_id"],
    )
    await conn.execute(
        "update sale_orders set approval_id = $2 where id = $1", order.row["id"], approval_id
    )
    return approval_id


async def apply_decision(conn: asyncpg.Connection, approval_id: UUID) -> str:
    """An owner or admin cleared a price under the floor — that price, on that
    order, if it is still the price."""
    approval = await conn.fetchrow(
        "select status, payload from approvals where id = $1 and kind = $2", approval_id, KIND
    )
    if approval is None or approval["status"] != "approved":
        return "not approved"
    payload = approval["payload"] or {}
    order = await load_order(conn, UUID(str(payload["order_id"])), lock=True)
    if (
        order is None
        or order.row["status"] != "quoted"
        or order.price_minor != payload.get("price_minor")
    ):
        return "stale"
    await conn.execute(
        "update sale_orders set approved_price_minor = $2 where id = $1",
        order.row["id"],
        order.price_minor,
    )
    return "applied"


# --------------------------------------------------------------------------
# taking payment, reserving, selling
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Paid:
    #: The deposit was completed by this payment and the car is now held.
    reserved: bool


async def record_payment(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    order: Order,
    *,
    stage: Stage,
    amount_minor: int,
    currency: str,
    fx_rate: Decimal,
    amount_tenant_minor: int,
    received_on: date,
    method: str,
    reference: str | None,
    document_path: str | None,
    source: str,
    actor_id: UUID,
) -> Paid:
    """Record money received. The payment that completes the deposit reserves
    the car — unless somebody else already holds it, which Postgres refuses."""
    if order.row["status"] not in ("quoted", "reserved"):
        raise Conflict(
            f"this order is {order.row['status']}",
            ar="لا يمكن تسجيل دفعة على هذا الطلب في حالته الحالية.",
        )
    if not order.cleared:
        raise Conflict(
            "this price is under the floor and an owner or admin has not approved it",
            ar="هذا السعر أقل من الحد الأدنى ولم يوافق عليه المالك أو المدير العام بعد.",
        )
    await conn.execute(
        """insert into sale_payments
             (tenant_id, order_id, stage, amount_minor, currency, fx_rate, amount_tenant_minor,
              received_on, method, reference, document_path, source, recorded_by)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
        tenant_id,
        order.row["id"],
        stage,
        amount_minor,
        currency,
        fx_rate,
        amount_tenant_minor,
        received_on,
        method,
        reference,
        document_path,
        source,
        actor_id,
    )
    if order.row["status"] != "quoted":
        return Paid(reserved=False)
    deposit_paid = amount_tenant_minor * (stage == "deposit") + sum(
        p["amount_tenant_minor"] for p in order.payments if p["stage"] == "deposit"
    )
    if deposit_paid < int(order.row["deposit_minor"]):
        return Paid(reserved=False)
    await reserve(conn, tenant_id, order)
    return Paid(reserved=True)


async def reserve(conn: asyncpg.Connection, tenant_id: UUID, order: Order) -> None:
    if order.vehicle_status not in ("available", "draft"):
        raise Conflict(
            f"the car is {order.vehicle_status} and cannot be reserved",
            ar="لا يمكن حجز السيارة في حالتها الحالية.",
        )
    try:
        async with conn.transaction():
            await conn.execute(
                "update sale_orders set status = 'reserved', reserved_at = now() where id = $1",
                order.row["id"],
            )
    except asyncpg.UniqueViolationError as exc:
        raise Conflict(
            "another buyer already holds this car",
            ar="مشترٍ آخر حجز هذه السيارة بالفعل.",
        ) from exc
    await _car_status(conn, tenant_id, order.row["vehicle_id"], "reserved", "deposit paid")


async def finish(conn: asyncpg.Connection, tenant_id: UUID, order: Order) -> None:
    """Every line paid: the car is sold."""
    if order.row["status"] != "reserved":
        raise Conflict(
            "only a reserved order can be completed",
            ar="لا يكتمل إلا الطلب المحجوز.",
        )
    left = order.schedule.outstanding_minor
    if left > 0:
        raise Conflict(
            f"{Money(left, order.row['currency']).display()} is still to be paid",
            ar=f"ما زال {Money(left, order.row['currency']).display()} غير مدفوع.",
        )
    await conn.execute(
        "update sale_orders set status = 'completed', completed_at = now() where id = $1",
        order.row["id"],
    )
    await conn.execute(
        "update vehicles set status = 'sold', sold_at = now() where id = $1",
        order.row["vehicle_id"],
    )
    await emit(
        conn,
        "vehicle.sold",
        {"vehicle_id": str(order.row["vehicle_id"]), "status": "sold", "reason": "order completed"},
        tenant_id=tenant_id,
        priority=5,
    )


async def cancel(conn: asyncpg.Connection, tenant_id: UUID, order: Order, reason: str) -> None:
    """The buyer walked away. A reserved car goes back on sale; what they paid
    stays on the record — a refund is a payment of its own, made elsewhere."""
    if order.row["status"] not in ("quoted", "reserved"):
        raise Conflict(
            f"this order is already {order.row['status']}",
            ar="هذا الطلب منتهٍ بالفعل.",
        )
    await conn.execute(
        """update sale_orders set status = 'cancelled', cancelled_at = now(), cancel_reason = $2
            where id = $1""",
        order.row["id"],
        reason,
    )
    if order.row["approval_id"] is not None:
        await conn.execute(
            """update approvals set status = 'rejected', decided_at = now(),
                      decision_note = 'order cancelled'
                where id = $1 and status = 'pending'""",
            order.row["approval_id"],
        )
    if order.row["status"] == "reserved" and order.vehicle_status == "reserved":
        await _car_status(conn, tenant_id, order.row["vehicle_id"], "available", "order cancelled")


async def _car_status(
    conn: asyncpg.Connection, tenant_id: UUID, vehicle_id: UUID, status: str, reason: str
) -> None:
    await conn.execute("update vehicles set status = $2 where id = $1", vehicle_id, status)
    await emit(
        conn,
        "vehicle.status_changed",
        {"vehicle_id": str(vehicle_id), "status": status, "reason": reason},
        tenant_id=tenant_id,
    )


# --------------------------------------------------------------------------
# a car that is no longer for sale is no longer marketed
# --------------------------------------------------------------------------

#: Content that has not reached the public yet, and can still be stopped.
UNPUBLISHED = ("draft", "rendering", "pending_approval", "approved", "scheduled")
#: A car in these states is not for sale to anybody else.
OFF_SALE = ("reserved", "sold", "archived")


async def stop_marketing(
    conn: asyncpg.Connection, vehicle_id: UUID, status: str
) -> dict[str, list[UUID]]:
    """Archive what has not been published about a car that is off sale, and
    list what has — a post already out is the dealer's to take down."""
    if status not in OFF_SALE:
        return {"stopped": [], "published": []}
    stopped = [
        row["id"]
        for row in await conn.fetch(
            """update content_items
                  set status = 'archived', rejection_reason = $2
                where vehicle_id = $1 and status = any($3::text[])
            returning id""",
            vehicle_id,
            f"the car is {status}",
            list(UNPUBLISHED),
        )
    ]
    published = [
        row["id"]
        for row in await conn.fetch(
            "select id from content_items where vehicle_id = $1 and status = 'published'",
            vehicle_id,
        )
    ]
    return {"stopped": stopped, "published": published}


# --------------------------------------------------------------------------
# reading a transfer receipt
# --------------------------------------------------------------------------


class ReceiptReading(BaseModel):
    """Text as printed; code parses and checks."""

    amount: str = Field(description="The amount transferred, exactly as printed.")
    amount_quote: str = Field(max_length=300, description="The printed line the amount is on.")
    currency: str = Field(min_length=3, max_length=3)
    paid_on: str | None = Field(default=None, description="Value or transfer date, YYYY-MM-DD.")
    reference: str | None = Field(default=None, max_length=120)
    reference_quote: str | None = Field(default=None, max_length=300)
    payer: str | None = Field(default=None, max_length=200)
    bank: str | None = Field(default=None, max_length=200)
    fx_rate: str | None = Field(default=None, description="Only if the receipt prints one.")
    fx_quote: str | None = Field(default=None, max_length=300)


@dataclass(slots=True)
class ReceiptProposal:
    amount_minor: int | None
    currency: str
    paid_on: date | None
    reference: str | None
    payer: str | None
    bank: str | None
    fx_rate: Decimal | None
    warnings: list[str] = field(default_factory=list)


def verify_receipt(reading: ReceiptReading) -> ReceiptProposal:
    """Keep what is provably on the receipt. Pure."""
    currency = reading.currency.strip().upper()
    warnings: list[str] = []
    amount_minor: int | None = None
    try:
        amount = parse_number(reading.amount)
        if amount not in numbers_in(reading.amount_quote):
            warnings.append(f"{reading.amount} does not appear in the line it was read from")
        elif amount <= 0:
            warnings.append(f"an amount of {reading.amount} is not a payment")
        else:
            amount_minor = Money.from_major(amount, currency).amount_minor
    except ValueError:
        warnings.append(f"could not read the amount {reading.amount!r}")

    reference = (reading.reference or "").strip() or None
    if reference and reading.reference_quote and reference not in reading.reference_quote:
        warnings.append(f"the reference {reference} does not appear where it was read")
        reference = None

    fx_rate: Decimal | None = None
    if reading.fx_rate:
        try:
            rate = parse_number(reading.fx_rate)
            if rate > 0 and reading.fx_quote and rate in numbers_in(reading.fx_quote):
                fx_rate = rate
            else:
                warnings.append(f"the exchange rate {reading.fx_rate} was not found where read")
        except ValueError:
            warnings.append(f"could not read the exchange rate {reading.fx_rate!r}")

    paid_on: date | None = None
    if reading.paid_on:
        try:
            paid_on = date.fromisoformat(reading.paid_on.strip()[:10])
        except ValueError:
            paid_on = None

    return ReceiptProposal(
        amount_minor=amount_minor,
        currency=currency,
        paid_on=paid_on,
        reference=reference,
        payer=(reading.payer or "").strip() or None,
        bank=(reading.bank or "").strip() or None,
        fx_rate=fx_rate,
        warnings=warnings,
    )


async def read_receipt(*, tenant_id: UUID, data: bytes, mime_type: str) -> ReceiptProposal:
    """Read one transfer receipt. One vision call; writes nothing."""
    result = await complete(
        TaskKind.VISION,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("payment_reader")),
        messages=types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=data, mime_type=mime_type),
                types.Part.from_text(text="Read this payment receipt."),
            ],
        ),
        output_schema=ReceiptReading,
        trace_name="payment_reader",
    )
    assert isinstance(result.parsed, ReceiptReading)  # noqa: S101 - schema-constrained
    proposal = verify_receipt(result.parsed)
    log.info(
        "receipt_read",
        read=proposal.amount_minor is not None,
        warnings=len(proposal.warnings),
        cost_usd=round(result.cost_usd, 6),
    )
    return proposal
