"""The deal desk: orders, their invoices, and the payments against them.
docs/lifecycle/README.md § L6.

`orders.edit` (owner, admin, manager, sales) quotes a buyer and corrects a
quote. `payments.record` (owner, admin, manager) records money received, which
is what reserves and then sells a car, and completes or cancels a held order.
A price under the floor waits for an owner or admin in the approvals queue.

An order is what the buyer agreed to pay — every member reads it. The margin on
it is the buy side, and is answered only on a session cleared for costs.view.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, Field

from ..core.errors import Conflict, Forbidden, NotFound, Unusable
from ..core.money import Money
from ..deps import Ctx, TenantContext, require_permission
from ..lifecycle import deals, export, invoices
from ..media import storage
from .acquisition import MoneyOut, _money, _rate, _session, _tenant_currency

log = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["deals"])

Seller = Annotated[TenantContext, Depends(require_permission("orders.edit"))]
Cashier = Annotated[TenantContext, Depends(require_permission("payments.record"))]

ChargeKind = Literal["fee", "freight", "duties", "other"]


class ChargeIn(BaseModel):
    kind: ChargeKind
    description: str | None = Field(default=None, max_length=300)
    amount_minor: int = Field(ge=0)


class OrderIn(BaseModel):
    buyer_name: str = Field(min_length=1, max_length=200)
    lead_id: UUID | None = None
    contact_id: UUID | None = None
    purchase_type: Literal["local", "export"]
    destination: str | None = Field(default=None, min_length=2, max_length=2)
    #: The car's agreed price, in the dealer's currency.
    price_minor: int = Field(ge=0)
    deposit_minor: int = Field(ge=0)
    charges: list[ChargeIn] = Field(default_factory=list, max_length=20)


class OrderPatch(BaseModel):
    buyer_name: str | None = Field(default=None, min_length=1, max_length=200)
    purchase_type: Literal["local", "export"] | None = None
    destination: str | None = Field(default=None, min_length=2, max_length=2)
    price_minor: int | None = Field(default=None, ge=0)
    deposit_minor: int | None = Field(default=None, ge=0)
    charges: list[ChargeIn] | None = Field(default=None, max_length=20)


class PaymentIn(BaseModel):
    stage: deals.Stage
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    #: Units of the dealer's currency per one unit of `currency`. Required when
    #: they differ — a rate is a fact somebody supplies, never looked up.
    fx_rate: str | None = Field(default=None, max_length=24)
    received_on: date
    method: Literal["bank_transfer", "cash", "card", "other"] = "bank_transfer"
    reference: str | None = Field(default=None, max_length=120)
    document_path: str | None = Field(default=None, max_length=500)


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ChargeOut(BaseModel):
    kind: str
    description: str | None
    amount: MoneyOut


class StageOut(BaseModel):
    stage: str
    due: MoneyOut
    paid: MoneyOut
    left: MoneyOut


class ScheduleOut(BaseModel):
    stages: list[StageOut]
    total: MoneyOut
    paid: MoneyOut
    outstanding: MoneyOut
    #: The first stage still owed: what the next payment is for.
    next_stage: str | None


class PaymentOut(BaseModel):
    id: UUID
    stage: str
    amount: MoneyOut
    amount_tenant: MoneyOut
    fx_rate: str
    received_on: date
    method: str
    reference: str | None
    source: str
    document_path: str | None


class OrderOut(BaseModel):
    id: UUID
    vehicle_id: UUID
    lead_id: UUID | None
    contact_id: UUID | None
    buyer_name: str
    purchase_type: str
    destination: str | None
    currency: str
    status: str
    price: MoneyOut
    floor: MoneyOut | None
    #: Anything may be taken against this price: at or over the floor, or
    #: approved at exactly this figure.
    cleared: bool
    #: An approval waiting on an owner or admin, when the price is under the floor.
    approval_id: UUID | None
    charges: list[ChargeOut]
    schedule: ScheduleOut
    payments: list[PaymentOut]
    #: Price less landed cost — the buy side, null for anyone not cleared.
    margin: MoneyOut | None
    reserved_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime


class ReceiptOut(BaseModel):
    amount: MoneyOut | None
    paid_on: date | None
    reference: str | None
    payer: str | None
    bank: str | None
    fx_rate: str | None
    #: The receipt is not in the dealer's currency and prints no rate.
    needs_fx_rate: bool
    #: What this payment is most likely for: the first stage still owed.
    stage: str | None
    warnings: list[str]
    document_path: str | None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


async def _present(
    conn: asyncpg.Connection, ctx: TenantContext, order: deals.Order
) -> dict[str, Any]:
    row = order.row
    currency = row["currency"]
    plan = order.schedule
    margin = None
    if ctx.may("costs.view"):
        economics = await conn.fetchrow(
            "select landed_cost_minor, cost_lines from v_vehicle_economics where vehicle_id = $1",
            row["vehicle_id"],
        )
        if economics and economics["cost_lines"]:
            margin = _money(order.price_minor - int(economics["landed_cost_minor"]), currency)
    pending = None
    if row["approval_id"] is not None and not order.cleared:
        pending = row["approval_id"]
    return {
        **{
            name: row[name]
            for name in (
                "id",
                "vehicle_id",
                "lead_id",
                "contact_id",
                "buyer_name",
                "purchase_type",
                "destination",
                "currency",
                "status",
                "reserved_at",
                "completed_at",
                "cancelled_at",
                "cancel_reason",
                "created_at",
            )
        },
        "price": _money(order.price_minor, currency),
        "floor": _money(order.floor_minor, currency),
        "cleared": order.cleared,
        "approval_id": pending,
        "charges": [
            {
                "kind": line["kind"],
                "description": line["description"],
                "amount": _money(line["amount_minor"], currency),
            }
            for line in order.lines
        ],
        "schedule": {
            "stages": [
                {
                    "stage": stage,
                    "due": _money(plan.due[stage], currency),
                    "paid": _money(plan.paid[stage], currency),
                    "left": _money(plan.left(stage), currency),
                }
                for stage in deals.STAGES
            ],
            "total": _money(plan.total_minor, currency),
            "paid": _money(plan.paid_minor, currency),
            "outstanding": _money(plan.outstanding_minor, currency),
            "next_stage": plan.next_stage,
        },
        "payments": [
            {
                "id": p["id"],
                "stage": p["stage"],
                "amount": _money(p["amount_minor"], p["currency"]),
                "amount_tenant": _money(p["amount_tenant_minor"], currency),
                "fx_rate": format(p["fx_rate"].normalize(), "f"),
                "received_on": p["received_on"],
                "method": p["method"],
                "reference": p["reference"],
                "source": p["source"],
                "document_path": p["document_path"],
            }
            for p in order.payments
        ],
        "margin": margin,
    }


async def _order(conn: asyncpg.Connection, order_id: UUID, *, lock: bool = False) -> deals.Order:
    order = await deals.load_order(conn, order_id, lock=lock)
    if order is None:
        raise NotFound("no such order", ar="لا يوجد طلب بهذا الرقم.")
    return order


def _check_invoice(
    purchase_type: str,
    destination: str | None,
    price_minor: int,
    deposit_minor: int,
    charges: list[ChargeIn],
) -> None:
    if purchase_type == "export" and not destination:
        raise Unusable(
            "an export order needs the country it is going to",
            ar="طلب التصدير يحتاج دولة الوجهة.",
        )
    fees = sum(c.amount_minor for c in charges if c.kind not in deals.LOGISTICS)
    if deposit_minor > price_minor + fees:
        raise Unusable(
            "the deposit cannot be more than the price",
            ar="العربون لا يمكن أن يكون أكبر من السعر.",
        )


def _charges(charges: list[ChargeIn]) -> list[deals.Charge]:
    return [deals.Charge(c.kind, c.description, c.amount_minor) for c in charges]


# --------------------------------------------------------------------------
# orders
# --------------------------------------------------------------------------


@router.get("/vehicles/{vehicle_id}/orders", response_model=list[OrderOut])
async def list_orders(vehicle_id: UUID, ctx: Ctx) -> list[dict[str, Any]]:
    async with _session(ctx) as conn:
        ids = await conn.fetch(
            "select id from sale_orders where vehicle_id = $1 order by created_at desc",
            vehicle_id,
        )
        return [await _present(conn, ctx, await _order(conn, r["id"])) for r in ids]


@router.post(
    "/vehicles/{vehicle_id}/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED
)
async def create_order(vehicle_id: UUID, body: OrderIn, ctx: Seller) -> dict[str, Any]:
    """Quote a buyer. Under the floor, the quote waits for an owner or admin
    before anything can be taken against it."""
    _check_invoice(
        body.purchase_type, body.destination, body.price_minor, body.deposit_minor, body.charges
    )
    async with _session(ctx) as conn, conn.transaction():
        car = await conn.fetchrow("select status from vehicles where id = $1", vehicle_id)
        if car is None:
            raise NotFound("no such vehicle", ar="لا توجد سيارة بهذا الرقم.")
        if car["status"] not in ("available", "draft"):
            raise Conflict(
                f"the car is {car['status']}",
                ar="هذه السيارة غير متاحة للبيع.",
            )
        for table, ref in (("leads", body.lead_id), ("contacts", body.contact_id)):
            if ref is not None and not await conn.fetchval(
                f"select 1 from {table} where id = $1",  # noqa: S608 - table is a literal above
                ref,
            ):
                raise NotFound(f"no such {table[:-1]}", ar="لا يوجد عميل أو فرصة بهذا الرقم.")
        currency = await _tenant_currency(conn, ctx.tenant_id)
        order_id = await conn.fetchval(
            """insert into sale_orders
                 (tenant_id, vehicle_id, lead_id, contact_id, buyer_name, purchase_type,
                  destination, currency, deposit_minor, created_by)
               values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) returning id""",
            ctx.tenant_id,
            vehicle_id,
            body.lead_id,
            body.contact_id,
            body.buyer_name.strip(),
            body.purchase_type,
            body.destination.upper() if body.destination else None,
            currency,
            body.deposit_minor,
            ctx.user.id,
        )
        await deals.write_charges(
            conn, ctx.tenant_id, order_id, body.price_minor, _charges(body.charges)
        )
        order = await _order(conn, order_id)
        if await deals.ask_if_under_floor(conn, ctx.tenant_id, order, currency=currency):
            order = await _order(conn, order_id)
        return await _present(conn, ctx, order)


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: UUID, ctx: Ctx) -> dict[str, Any]:
    async with _session(ctx) as conn:
        return await _present(conn, ctx, await _order(conn, order_id))


@router.patch("/orders/{order_id}", response_model=OrderOut)
async def update_order(order_id: UUID, body: OrderPatch, ctx: Seller) -> dict[str, Any]:
    """Correct a quote. Once a deposit holds the car, the invoice is what was agreed."""
    changes = body.model_dump(exclude_unset=True)
    async with _session(ctx) as conn, conn.transaction():
        order = await _order(conn, order_id, lock=True)
        if order.row["status"] != "quoted":
            raise Conflict(
                "only a quote can be changed; cancel it and quote again",
                ar="لا يُعدَّل إلا عرض السعر؛ ألغِه وأنشئ عرضًا جديدًا.",
            )
        charges = (
            body.charges
            if body.charges is not None
            else [
                ChargeIn(
                    kind=line["kind"],
                    description=line["description"],
                    amount_minor=line["amount_minor"],
                )
                for line in order.lines
                if line["kind"] != "vehicle"
            ]
        )
        price = changes.get("price_minor", order.price_minor)
        deposit = changes.get("deposit_minor", order.row["deposit_minor"])
        purchase_type = changes.get("purchase_type", order.row["purchase_type"])
        destination = changes.get("destination", order.row["destination"])
        _check_invoice(purchase_type, destination, price, deposit, charges)
        await conn.execute(
            """update sale_orders set buyer_name = $2, purchase_type = $3, destination = $4,
                      deposit_minor = $5
                where id = $1""",
            order_id,
            changes.get("buyer_name", order.row["buyer_name"]),
            purchase_type,
            destination.upper() if destination else None,
            deposit,
        )
        await deals.write_charges(conn, ctx.tenant_id, order_id, price, _charges(charges))
        order = await _order(conn, order_id)
        if await deals.ask_if_under_floor(
            conn, ctx.tenant_id, order, currency=order.row["currency"]
        ):
            order = await _order(conn, order_id)
        return await _present(conn, ctx, order)


# --------------------------------------------------------------------------
# payments
# --------------------------------------------------------------------------


def _payment_path_ok(ctx: TenantContext, path: str | None) -> None:
    if path is not None and not path.startswith(f"{ctx.tenant_id}/payments/"):
        raise Unusable(
            "that receipt is not one of this dealership's",
            ar="هذا الإيصال ليس من إيصالات هذا المعرض.",
        )


@router.post("/orders/{order_id}/payments", response_model=OrderOut)
async def record_payment(order_id: UUID, body: PaymentIn, ctx: Cashier) -> dict[str, Any]:
    """Record money received. The payment that completes the deposit reserves the car."""
    _payment_path_ok(ctx, body.document_path)
    async with _session(ctx) as conn, conn.transaction():
        order = await _order(conn, order_id, lock=True)
        currency = body.currency.upper()
        rate = _rate(currency, order.row["currency"], body.fx_rate)
        converted = Money(body.amount_minor, currency).convert(rate, order.row["currency"])
        paid = await deals.record_payment(
            conn,
            ctx.tenant_id,
            order,
            stage=body.stage,
            amount_minor=body.amount_minor,
            currency=currency,
            fx_rate=rate,
            amount_tenant_minor=converted.amount_minor,
            received_on=body.received_on,
            method=body.method,
            reference=body.reference,
            document_path=body.document_path,
            source="document" if body.document_path else "manual",
            actor_id=ctx.user.id,
        )
        if paid.reserved:
            # Held: the export file — or a local sale's handover — starts now,
            # with step one, asking the buyer for their documents.
            await export.start(conn, ctx.tenant_id, order_id)
            log.info("vehicle_reserved", order_id=str(order_id))
        return await _present(conn, ctx, await _order(conn, order_id))


@router.post("/orders/{order_id}/payments/read", response_model=ReceiptOut)
async def read_receipt(
    order_id: UUID, ctx: Cashier, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """Read a transfer receipt into a proposed payment. Records nothing."""
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in invoices.MIME_TYPES:
        raise Unusable(
            "a receipt is a photograph (JPEG, PNG, WebP) or a PDF",
            ar="الإيصال يكون صورة (JPEG أو PNG أو WebP) أو ملف PDF.",
        )
    data = await file.read()
    if not data or len(data) > invoices.MAX_BYTES:
        raise Unusable(
            "a receipt must be under 15 MB and not empty",
            ar="الإيصال يجب ألا يكون فارغًا وأن يكون أصغر من ١٥ ميجابايت.",
        )
    async with _session(ctx) as conn:
        order = await _order(conn, order_id)
    proposal = await deals.read_receipt(tenant_id=ctx.tenant_id, data=data, mime_type=mime)

    path = storage.object_path(
        ctx.tenant_id, "payments", storage.extension_for(mime, file.filename)
    )
    document_path: str | None = path
    try:
        await storage.upload(path, data, content_type=mime)
    except Exception as exc:  # noqa: BLE001 - the reading is still worth showing
        log.warning("receipt_not_stored", error=str(exc))
        proposal.warnings.append("the receipt could not be kept; the reading is still usable")
        document_path = None
    return {
        "amount": _money(proposal.amount_minor, proposal.currency),
        "paid_on": proposal.paid_on,
        "reference": proposal.reference,
        "payer": proposal.payer,
        "bank": proposal.bank,
        "fx_rate": format(proposal.fx_rate, "f") if proposal.fx_rate else None,
        "needs_fx_rate": proposal.currency != order.row["currency"] and proposal.fx_rate is None,
        "stage": order.schedule.next_stage,
        "warnings": proposal.warnings,
        "document_path": document_path,
    }


# --------------------------------------------------------------------------
# finishing
# --------------------------------------------------------------------------


@router.post("/orders/{order_id}/complete", response_model=OrderOut)
async def complete_order(order_id: UUID, ctx: Cashier) -> dict[str, Any]:
    """Every line of the invoice paid: the car is sold."""
    async with _session(ctx) as conn, conn.transaction():
        await deals.finish(conn, ctx.tenant_id, await _order(conn, order_id, lock=True))
        return await _present(conn, ctx, await _order(conn, order_id))


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(order_id: UUID, body: CancelIn, ctx: Seller) -> dict[str, Any]:
    """The buyer walked away. Letting go of a car somebody paid to hold is the
    cashier's call, not the salesperson's."""
    async with _session(ctx) as conn, conn.transaction():
        order = await _order(conn, order_id, lock=True)
        if order.row["status"] == "reserved" and not ctx.may("payments.record"):
            raise Forbidden(
                "cancelling a reserved order needs an owner, admin or manager",
                ar="إلغاء طلب محجوز للمالك أو المدير العام أو المدير فقط.",
            )
        await deals.cancel(conn, ctx.tenant_id, order, body.reason.strip())
        return await _present(conn, ctx, await _order(conn, order_id))
