"""The buy side of a vehicle: how it was bought, what it cost, what it makes.

Every route here opens its session cleared for the buy side only when the caller
holds `costs.view` — and the rows themselves are invisible in Postgres to any
other person's session (0016_lifecycle_acquisition.sql). The permission check
is the door; the policy is the wall behind it.

Reading an invoice is a proposal. `/costs/extract` returns lines and writes
nothing; `POST /costs` writes what the person posted back. There is no path from
a model's reading to a stored cost that a person did not look at.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field

from ..core.errors import NotFound, Unusable
from ..core.money import Money, exponent
from ..db.session import tenant_session
from ..deps import TenantContext, require_permission
from ..lifecycle import invoices, numbers, pricing
from ..media import storage

log = structlog.get_logger()

router = APIRouter(prefix="/v1/vehicles", tags=["acquisition"])

Viewer = Annotated[TenantContext, Depends(require_permission("costs.view"))]
Editor = Annotated[TenantContext, Depends(require_permission("costs.edit"))]

Source = Literal["auction", "trade_in", "private", "dealer", "import", "other"]
Category = invoices.Category
Status = Literal["estimate", "actual"]


class MoneyOut(BaseModel):
    amount_minor: int
    currency: str


class Acquisition(BaseModel):
    source: Source
    seller: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=120)
    purchased_at: date
    notes: str | None = Field(default=None, max_length=2000)


class AcquisitionOut(Acquisition):
    vehicle_id: UUID
    updated_at: datetime


class CostIn(BaseModel):
    category: Category
    description: str | None = Field(default=None, max_length=300)
    vendor: str | None = Field(default=None, max_length=200)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    #: Units of the dealer's currency per one unit of `currency`, as a string so
    #: it is never a float. Required when the currencies differ.
    fx_rate: str | None = Field(default=None, max_length=24)
    incurred_at: date
    status: Status = "actual"
    source: Literal["manual", "document"] = "manual"
    document_path: str | None = Field(default=None, max_length=500)


class CostBatch(BaseModel):
    lines: list[CostIn] = Field(min_length=1, max_length=100)


class CostPatch(BaseModel):
    category: Category | None = None
    description: str | None = Field(default=None, max_length=300)
    vendor: str | None = Field(default=None, max_length=200)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate: str | None = Field(default=None, max_length=24)
    incurred_at: date | None = None
    status: Status | None = None


class CostOut(BaseModel):
    id: UUID
    category: str
    description: str | None
    vendor: str | None
    amount: MoneyOut
    fx_rate: str
    amount_tenant: MoneyOut
    incurred_at: date
    status: str
    source: str
    document_path: str | None
    created_at: datetime


class Economics(BaseModel):
    vehicle_id: UUID
    status: str
    days_in_stock: int
    cost_actual: MoneyOut
    cost_estimate: MoneyOut
    landed_cost: MoneyOut
    cost_lines: int
    has_acquisition: bool
    price: MoneyOut | None
    floor: MoneyOut | None
    margin_at_price: MoneyOut | None
    margin_at_floor: MoneyOut | None
    #: Margin as a share of the price, in basis points. An integer, so a client
    #: never formats a float that says 12.000000000000002 percent.
    margin_bps_at_price: int | None
    #: Why a margin is missing, when it is. "No cost recorded" and "the price is
    #: in another currency" are different problems with different fixes.
    margin_note: str | None
    #: From the purchase (or the listing) to the sale, or to today — L8.
    days_held: int
    #: What keeping the car has cost so far, at the dealer's holding rate.
    holding_cost: MoneyOut


class ProposedLineOut(BaseModel):
    category: str
    description: str
    amount_minor: int
    currency: str
    quote: str


class ExtractionOut(BaseModel):
    currency: str
    tenant_currency: str
    vendor: str | None
    reference: str | None
    incurred_at: date | None
    lines: list[ProposedLineOut]
    total_minor: int | None
    fx_rate: str | None
    #: True when the document's currency is not the dealer's and no rate was
    #: printed on it: the person has to supply one before confirming.
    needs_fx_rate: bool
    warnings: list[str]
    document_path: str | None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _session(ctx: TenantContext) -> AbstractAsyncContextManager[asyncpg.Connection]:
    return tenant_session(
        ctx.tenant_id,
        user_id=ctx.user.id,
        scope=ctx.scope,
        buy_side=ctx.may("costs.view"),
    )


def _money(amount: int | None, currency: str) -> dict[str, Any] | None:
    return None if amount is None else {"amount_minor": int(amount), "currency": currency}


async def _vehicle(conn: asyncpg.Connection, vehicle_id: UUID) -> asyncpg.Record:
    row = await conn.fetchrow(
        "select id, currency, price_minor, min_price_minor from vehicles where id = $1",
        vehicle_id,
    )
    if row is None:
        raise NotFound("no such vehicle", ar="لا توجد سيارة بهذا الرقم.")
    return row


async def _tenant_currency(conn: asyncpg.Connection, tenant_id: UUID) -> str:
    return str(await conn.fetchval("select currency from tenants where id = $1", tenant_id))


def _rate(line_currency: str, tenant_currency: str, raw: str | None) -> Decimal:
    """The rate to store, or a refusal that says what is missing.

    Same currency is exactly 1, whatever was sent. A different currency needs a
    rate from the person: this never looks one up, because a rate is a fact
    with a source and the source here is the person or the document.
    """
    if line_currency == tenant_currency:
        return Decimal(1)
    if not raw:
        raise Unusable(
            f"a cost in {line_currency} needs the exchange rate to {tenant_currency}",
            ar=f"التكلفة بعملة {line_currency} تحتاج سعر الصرف إلى {tenant_currency}.",
        )
    try:
        rate = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise Unusable(
            f"{raw!r} is not an exchange rate",
            ar=f"«{raw}» ليس سعر صرف صالحًا.",
        ) from exc
    if rate <= 0:
        raise Unusable("an exchange rate must be positive", ar="سعر الصرف يجب أن يكون أكبر من صفر.")
    return rate


def _document_path_ok(ctx: TenantContext, path: str | None) -> None:
    """A stored invoice must be this tenant's and an invoice.

    The path comes back from the browser, so it is input like any other: without
    this a line could point at another dealership's object, or at a customer's
    voice note, and the screen would offer it as the invoice.
    """
    if path is not None and not path.startswith(f"{ctx.tenant_id}/invoices/"):
        raise Unusable(
            "that document is not one of this dealership's invoices",
            ar="هذا المستند ليس من فواتير هذا المعرض.",
        )


def _present_cost(row: Any, tenant_currency: str) -> dict[str, Any]:
    return {
        "id": row["id"],
        "category": row["category"],
        "description": row["description"],
        "vendor": row["vendor"],
        "amount": _money(row["amount_minor"], row["currency"]),
        "fx_rate": format(row["fx_rate"].normalize(), "f"),
        "amount_tenant": _money(row["amount_tenant_minor"], tenant_currency),
        "incurred_at": row["incurred_at"],
        "status": row["status"],
        "source": row["source"],
        "document_path": row["document_path"],
        "created_at": row["created_at"],
    }


async def _audit(
    conn: asyncpg.Connection,
    ctx: TenantContext,
    action: str,
    cost_id: UUID,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Every change to what a car cost is answerable. Money moved on paper is
    still money: a margin that changed overnight needs a name beside it."""
    await conn.execute(
        """insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type,
                                  entity_id, before, after)
           values ($1, 'user', $2, $3, 'vehicle_cost', $4, $5, $6)""",
        ctx.tenant_id,
        str(ctx.user.id),
        action,
        cost_id,
        before,
        after,
    )


def _plain(row: Any) -> dict[str, Any]:
    """A row as JSON audit_log can hold."""
    return {
        k: (str(v) if isinstance(v, UUID | Decimal | date | datetime) else v)
        for k, v in dict(row).items()
    }


_COST_COLUMNS = """id, category, description, vendor, amount_minor, currency, fx_rate,
    amount_tenant_minor, incurred_at, status, source, document_path, created_at"""


# --------------------------------------------------------------------------
# acquisition
# --------------------------------------------------------------------------


@router.get("/{vehicle_id}/acquisition", response_model=AcquisitionOut | None)
async def get_acquisition(vehicle_id: UUID, ctx: Viewer) -> dict[str, Any] | None:
    """How the car was bought, or null if nobody has recorded it yet."""
    async with _session(ctx) as conn:
        await _vehicle(conn, vehicle_id)
        row = await conn.fetchrow(
            """select vehicle_id, source, seller, reference, purchased_at, notes, updated_at
                 from vehicle_acquisitions where vehicle_id = $1""",
            vehicle_id,
        )
    return dict(row) if row else None


@router.put("/{vehicle_id}/acquisition", response_model=AcquisitionOut)
async def put_acquisition(vehicle_id: UUID, body: Acquisition, ctx: Editor) -> dict[str, Any]:
    async with _session(ctx) as conn:
        await _vehicle(conn, vehicle_id)
        row = await conn.fetchrow(
            """insert into vehicle_acquisitions
                 (vehicle_id, tenant_id, source, seller, reference, purchased_at, notes,
                  created_by)
               values ($1,$2,$3,$4,$5,$6,$7,$8)
               on conflict (vehicle_id) do update set
                 source = excluded.source, seller = excluded.seller,
                 reference = excluded.reference, purchased_at = excluded.purchased_at,
                 notes = excluded.notes
               returning vehicle_id, source, seller, reference, purchased_at, notes,
                         updated_at""",
            vehicle_id,
            ctx.tenant_id,
            body.source,
            body.seller,
            body.reference,
            body.purchased_at,
            body.notes,
            ctx.user.id,
        )
    return dict(row)


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------


@router.get("/{vehicle_id}/costs", response_model=list[CostOut])
async def list_costs(vehicle_id: UUID, ctx: Viewer) -> list[dict[str, Any]]:
    async with _session(ctx) as conn:
        await _vehicle(conn, vehicle_id)
        tenant_currency = await _tenant_currency(conn, ctx.tenant_id)
        rows = await conn.fetch(
            f"select {_COST_COLUMNS} from vehicle_costs where vehicle_id = $1 "  # noqa: S608
            "order by incurred_at, created_at",
            vehicle_id,
        )
    return [_present_cost(r, tenant_currency) for r in rows]


@router.post(
    "/{vehicle_id}/costs", response_model=list[CostOut], status_code=status.HTTP_201_CREATED
)
async def add_costs(vehicle_id: UUID, body: CostBatch, ctx: Editor) -> list[dict[str, Any]]:
    """Record cost lines — typed by hand, or confirmed from a reading.

    All or nothing: a batch is one invoice, and half an invoice recorded is a
    landed cost that is wrong by an amount nobody can see.
    """
    for line in body.lines:
        _document_path_ok(ctx, line.document_path)

    out: list[dict[str, Any]] = []
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        tenant_currency = await _tenant_currency(conn, ctx.tenant_id)
        for line in body.lines:
            currency = line.currency.upper()
            rate = _rate(currency, tenant_currency, line.fx_rate)
            converted = Money(line.amount_minor, currency).convert(rate, tenant_currency)
            row = await conn.fetchrow(
                f"""insert into vehicle_costs
                      (tenant_id, vehicle_id, category, description, vendor, amount_minor,
                       currency, fx_rate, amount_tenant_minor, incurred_at, status, source,
                       document_path, created_by)
                    values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    returning {_COST_COLUMNS}""",  # noqa: S608
                ctx.tenant_id,
                vehicle_id,
                line.category,
                line.description,
                line.vendor,
                line.amount_minor,
                currency,
                rate,
                converted.amount_minor,
                line.incurred_at,
                line.status,
                line.source,
                line.document_path,
                ctx.user.id,
            )
            await _audit(conn, ctx, "vehicle_cost.created", row["id"], after=_plain(row))
            out.append(_present_cost(row, tenant_currency))
    log.info("costs_recorded", vehicle_id=str(vehicle_id), lines=len(out))
    return out


@router.patch("/{vehicle_id}/costs/{cost_id}", response_model=CostOut)
async def update_cost(
    vehicle_id: UUID, cost_id: UUID, body: CostPatch, ctx: Editor
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    async with _session(ctx) as conn, conn.transaction():
        tenant_currency = await _tenant_currency(conn, ctx.tenant_id)
        before = await conn.fetchrow(
            f"select {_COST_COLUMNS} from vehicle_costs "  # noqa: S608
            "where id = $1 and vehicle_id = $2 for update",
            cost_id,
            vehicle_id,
        )
        if before is None:
            raise NotFound("no such cost line", ar="لا يوجد بند تكلفة بهذا الرقم.")

        merged = {**dict(before), **{k: v for k, v in changes.items() if k != "fx_rate"}}
        currency = str(merged["currency"]).upper()
        # The amount in the dealer's currency is derived, never patched: it is
        # recomputed from whatever the amount, currency and rate now are.
        raw_rate = changes.get("fx_rate") or (
            None if "currency" in changes else format(before["fx_rate"], "f")
        )
        rate = _rate(currency, tenant_currency, raw_rate)
        converted = Money(int(merged["amount_minor"]), currency).convert(rate, tenant_currency)

        row = await conn.fetchrow(
            f"""update vehicle_costs set
                  category = $2, description = $3, vendor = $4, amount_minor = $5,
                  currency = $6, fx_rate = $7, amount_tenant_minor = $8,
                  incurred_at = $9, status = $10
                where id = $1
                returning {_COST_COLUMNS}""",  # noqa: S608
            cost_id,
            merged["category"],
            merged["description"],
            merged["vendor"],
            merged["amount_minor"],
            currency,
            rate,
            converted.amount_minor,
            merged["incurred_at"],
            merged["status"],
        )
        await _audit(
            conn, ctx, "vehicle_cost.updated", cost_id, before=_plain(before), after=_plain(row)
        )
    return _present_cost(row, tenant_currency)


@router.delete("/{vehicle_id}/costs/{cost_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cost(vehicle_id: UUID, cost_id: UUID, ctx: Editor) -> None:
    async with _session(ctx) as conn, conn.transaction():
        before = await conn.fetchrow(
            f"delete from vehicle_costs where id = $1 and vehicle_id = $2 "  # noqa: S608
            f"returning {_COST_COLUMNS}",
            cost_id,
            vehicle_id,
        )
        if before is None:
            raise NotFound("no such cost line", ar="لا يوجد بند تكلفة بهذا الرقم.")
        await _audit(conn, ctx, "vehicle_cost.deleted", cost_id, before=_plain(before))


# --------------------------------------------------------------------------
# unit economics
# --------------------------------------------------------------------------

_ECONOMICS = """
select vehicle_id, status, currency, price_minor, min_price_minor, days_in_stock,
       cost_actual_minor, cost_estimate_minor, landed_cost_minor, cost_lines,
       has_acquisition, days_held
  from v_vehicle_economics
"""


def _economics(row: Any, tenant_currency: str, settings: pricing.PricingSettings) -> dict[str, Any]:
    landed = int(row["landed_cost_minor"])
    holding = numbers.holding_minor(
        landed,
        int(row["days_held"]),
        rate_bps=settings.holding_rate_bps,
        per_day_minor=settings.holding_per_day_major * 10 ** exponent(tenant_currency),
    )
    same_currency = row["currency"] == tenant_currency
    note: str | None = None
    if row["cost_lines"] == 0:
        note = "no cost recorded"
    elif not same_currency:
        note = f"the price is in {row['currency']} and the costs in {tenant_currency}"

    def margin(amount: int | None) -> dict[str, Any] | None:
        if amount is None or note is not None:
            return None
        return _money(amount - landed, tenant_currency)

    price = row["price_minor"]
    bps = None
    if price and note is None:
        bps = round((price - landed) * 10_000 / price)
    return {
        "vehicle_id": row["vehicle_id"],
        "status": row["status"],
        "days_in_stock": row["days_in_stock"],
        "cost_actual": _money(row["cost_actual_minor"], tenant_currency),
        "cost_estimate": _money(row["cost_estimate_minor"], tenant_currency),
        "landed_cost": _money(landed, tenant_currency),
        "cost_lines": row["cost_lines"],
        "has_acquisition": row["has_acquisition"],
        "price": _money(price, row["currency"]),
        "floor": _money(row["min_price_minor"], row["currency"]),
        "margin_at_price": margin(price),
        "margin_at_floor": margin(row["min_price_minor"]),
        "margin_bps_at_price": bps,
        "margin_note": note,
        "days_held": row["days_held"],
        "holding_cost": _money(holding, tenant_currency),
    }


@router.get("/economics", response_model=list[Economics])
async def list_economics(ctx: Viewer) -> list[dict[str, Any]]:
    """Landed cost and margin for every car, for the inventory screen's columns."""
    async with _session(ctx) as conn:
        tenant_currency = await _tenant_currency(conn, ctx.tenant_id)
        settings = await pricing.settings_for(conn, ctx.tenant_id)
        rows = await conn.fetch(
            _ECONOMICS + " where tenant_id = $1 order by days_in_stock desc", ctx.tenant_id
        )
    return [_economics(r, tenant_currency, settings) for r in rows]


@router.get("/{vehicle_id}/economics", response_model=Economics)
async def get_economics(vehicle_id: UUID, ctx: Viewer) -> dict[str, Any]:
    async with _session(ctx) as conn:
        tenant_currency = await _tenant_currency(conn, ctx.tenant_id)
        settings = await pricing.settings_for(conn, ctx.tenant_id)
        row = await conn.fetchrow(_ECONOMICS + " where vehicle_id = $1", vehicle_id)
    if row is None:
        raise NotFound("no such vehicle", ar="لا توجد سيارة بهذا الرقم.")
    return _economics(row, tenant_currency, settings)


# --------------------------------------------------------------------------
# reading an invoice
# --------------------------------------------------------------------------


@router.post("/{vehicle_id}/costs/extract", response_model=ExtractionOut)
async def extract_costs(
    vehicle_id: UUID,
    ctx: Editor,
    file: Annotated[UploadFile, File()],
    note: Annotated[str | None, Form(max_length=300)] = None,
) -> dict[str, Any]:
    """Read a purchase document into proposed cost lines. Writes nothing.

    The vehicle is described to the model so it can pick this car's lines out of
    a shipping invoice that covers a whole container.
    """
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in invoices.MIME_TYPES:
        raise Unusable(
            "a document is a photograph (JPEG, PNG, WebP) or a PDF",
            ar="المستند يكون صورة (JPEG أو PNG أو WebP) أو ملف PDF.",
        )
    data = await file.read()
    if len(data) > invoices.MAX_BYTES:
        raise Unusable("that document is larger than 15 MB", ar="المستند أكبر من ١٥ ميجابايت.")
    if not data:
        raise Unusable("that document is empty", ar="المستند فارغ.")

    async with _session(ctx) as conn:
        vehicle = await conn.fetchrow(
            "select make, model, model_year, vin, stock_number from vehicles where id = $1",
            vehicle_id,
        )
        if vehicle is None:
            raise NotFound("no such vehicle", ar="لا توجد سيارة بهذا الرقم.")
        tenant_currency = await _tenant_currency(conn, ctx.tenant_id)

    described = " ".join(
        str(part) for part in (vehicle["model_year"], vehicle["make"], vehicle["model"]) if part
    )
    if vehicle["vin"]:
        described += f", VIN {vehicle['vin']}"
    if vehicle["stock_number"]:
        described += f", stock {vehicle['stock_number']}"
    hint = f"This document is for one vehicle: {described}."
    if note:
        hint += f" The dealer adds: {note}"

    proposal = await invoices.read(tenant_id=ctx.tenant_id, data=data, mime_type=mime, hint=hint)

    # Kept after the reading, so a reading that failed leaves no file behind.
    # ponytail: a reading nobody confirms still leaves its invoice in storage;
    # sweep `invoices/` objects no cost line points at if that ever matters.
    document_path: str | None = None
    try:
        document_path = storage.object_path(
            ctx.tenant_id, "invoices", storage.extension_for(mime, file.filename)
        )
        await storage.upload(document_path, data, content_type=mime)
    except Exception as exc:  # noqa: BLE001 - the reading is still worth showing
        log.warning("invoice_not_stored", error=str(exc))
        proposal.warnings.append("the document could not be kept; the lines are still usable")
        document_path = None

    return {
        "currency": proposal.currency,
        "tenant_currency": tenant_currency,
        "vendor": proposal.vendor,
        "reference": proposal.reference,
        "incurred_at": proposal.incurred_at,
        "lines": [
            {
                "category": line.category,
                "description": line.description,
                "amount_minor": line.amount_minor,
                "currency": line.currency,
                "quote": line.quote,
            }
            for line in proposal.lines
        ],
        "total_minor": proposal.total_minor,
        "fx_rate": format(proposal.fx_rate, "f") if proposal.fx_rate else None,
        "needs_fx_rate": proposal.currency != tenant_currency and proposal.fx_rate is None,
        "warnings": proposal.warnings,
        "document_path": document_path,
    }


# --------------------------------------------------------------------------
# pricing — docs/lifecycle/README.md § L2
# --------------------------------------------------------------------------


class RecommendationOut(BaseModel):
    action: str
    price: MoneyOut | None
    floor: MoneyOut | None
    ideal: MoneyOut | None
    target: MoneyOut | None
    reasons: list[str]
    #: A proposal already waiting in the approvals queue for this car.
    pending_approval_id: UUID | None


class ProposalOut(BaseModel):
    approval_id: UUID | None
    #: Why nothing was proposed, when nothing was: the price is already where
    #: it should be, or a proposal is already waiting.
    note: str | None


async def _recommendation(
    conn: asyncpg.Connection, ctx: TenantContext, vehicle_id: UUID
) -> tuple[pricing.Facts, pricing.Recommendation]:
    facts = await pricing.facts_for(conn, vehicle_id)
    if facts is None:
        raise NotFound("no such vehicle", ar="لا توجد سيارة بهذا الرقم.")
    settings = await pricing.settings_for(conn, ctx.tenant_id)
    return facts, pricing.recommend(facts, settings)


@router.get("/{vehicle_id}/pricing", response_model=RecommendationOut)
async def get_pricing(vehicle_id: UUID, ctx: Viewer) -> dict[str, Any]:
    """What the price should be now, and why. Changes nothing."""
    async with _session(ctx) as conn:
        _facts, rec = await _recommendation(conn, ctx, vehicle_id)
        pending = await conn.fetchval(
            """select id from approvals
                where entity_id = $1 and kind = $2 and status = 'pending'""",
            vehicle_id,
            pricing.KIND,
        )
    return {
        "action": rec.action,
        "price": _money(rec.price_minor, rec.currency),
        "floor": _money(rec.floor_minor, rec.currency),
        "ideal": _money(rec.ideal_minor, rec.currency),
        "target": _money(rec.target_minor, rec.currency),
        "reasons": rec.reasons,
        "pending_approval_id": pending,
    }


@router.post("/{vehicle_id}/pricing/propose", response_model=ProposalOut)
async def propose_pricing(vehicle_id: UUID, ctx: Viewer) -> dict[str, Any]:
    """Put today's recommendation in the approvals queue now, rather than at
    tomorrow's sweep. Whoever may change prices still decides."""
    async with _session(ctx) as conn, conn.transaction():
        facts, rec = await _recommendation(conn, ctx, vehicle_id)
        approval_id = await pricing.propose(conn, ctx.tenant_id, vehicle_id, rec, facts=facts)
    if approval_id is not None:
        return {"approval_id": approval_id, "note": None}
    note = (
        "nothing to propose: " + rec.action
        if rec.action not in pricing.PROPOSED
        else "a proposal for this car is already waiting"
    )
    return {"approval_id": None, "note": note}


settings_router = APIRouter(prefix="/v1/settings/pricing", tags=["acquisition"])


@settings_router.get("", response_model=pricing.PricingSettings)
async def get_pricing_settings(
    ctx: Annotated[TenantContext, Depends(require_permission("settings.pricing"))],
) -> pricing.PricingSettings:
    async with _session(ctx) as conn:
        return await pricing.settings_for(conn, ctx.tenant_id)


@settings_router.put("", response_model=pricing.PricingSettings)
async def put_pricing_settings(
    body: pricing.PricingRules,
    ctx: Annotated[TenantContext, Depends(require_permission("settings.pricing"))],
) -> pricing.PricingSettings:
    # Checked here rather than left to the model: a validation error reaches
    # the screen as "a field failed", and this one needs saying in words.
    if body.floor_margin_bps > body.target_margin_bps:
        raise Unusable(
            "the floor's margin cannot be above the target margin",
            ar="هامش الحد الأدنى لا يمكن أن يكون أعلى من الهامش المستهدف.",
        )
    settings = pricing.PricingSettings.model_validate(body.model_dump())
    async with _session(ctx) as conn:
        await conn.execute(
            "update tenants set pricing_settings = $2 where id = $1",
            ctx.tenant_id,
            settings.model_dump(),
        )
    return settings
