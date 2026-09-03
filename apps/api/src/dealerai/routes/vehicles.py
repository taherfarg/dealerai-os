from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from ..core.errors import Conflict, NotFound
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_role
from ..events.bus import emit

router = APIRouter(prefix="/v1/vehicles", tags=["vehicles"])

VehicleStatus = Literal["draft", "available", "reserved", "sold", "archived"]
Condition = Literal["new", "used", "certified"]


class Money(BaseModel):
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)


class VehicleSummary(BaseModel):
    """What a customer-facing agent is allowed to see.

    `min_price_minor` is deliberately absent. It is the discount floor, and a
    Sales Agent that can read it will reason its way down to it. The agent is
    told a limit it may go to; it never sees the floor itself.
    See docs/03-database-schema.md § 3.
    """

    id: UUID
    make: str
    model: str
    trim: str | None = None
    model_year: int | None = None
    vehicle_condition: Condition
    mileage_km: int
    price: Money | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    engine: str | None = None
    transmission: str | None = None
    fuel: str | None = None
    seats: int | None = None
    features: list[str]
    status: VehicleStatus
    steering: Literal["lhd", "rhd"]
    target_markets: list[str]


class VehicleOut(VehicleSummary):
    """The internal view. Only staff endpoints return this."""

    stock_number: str | None = None
    vin: str | None = None
    min_price: Money | None = None
    specs: dict[str, Any]
    location: str | None = None
    listed_at: datetime
    sold_at: datetime | None = None
    source: str


class VehicleCreate(BaseModel):
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    trim: str | None = None
    model_year: int | None = Field(default=None, ge=1950, le=2100)
    vehicle_condition: Condition = "new"
    mileage_km: int = Field(default=0, ge=0)
    price_minor: int | None = Field(default=None, ge=0)
    min_price_minor: int | None = Field(default=None, ge=0)
    stock_number: str | None = None
    vin: str | None = Field(default=None, max_length=17)
    engine: str | None = None
    transmission: str | None = None
    fuel: str | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    seats: int | None = Field(default=None, ge=1, le=20)
    features: list[str] = Field(default_factory=list)
    specs: dict[str, Any] = Field(default_factory=dict)
    target_markets: list[str] = Field(default_factory=lambda: ["AE"])
    steering: Literal["lhd", "rhd"] = "lhd"
    location: str | None = None


class VehicleUpdate(BaseModel):
    trim: str | None = None
    mileage_km: int | None = Field(default=None, ge=0)
    min_price_minor: int | None = Field(default=None, ge=0)
    engine: str | None = None
    transmission: str | None = None
    fuel: str | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    seats: int | None = None
    features: list[str] | None = None
    specs: dict[str, Any] | None = None
    target_markets: list[str] | None = None
    location: str | None = None


class StatusChange(BaseModel):
    status: VehicleStatus
    reason: str | None = Field(default=None, max_length=500)


class PriceChange(BaseModel):
    amount_minor: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)


class StockRow(BaseModel):
    id: UUID
    make: str
    model: str
    stock_number: str | None
    status: VehicleStatus
    price: Money | None
    days_in_stock: int
    published_content_count: int
    last_content_at: datetime | None


_COLUMNS = """
    id, make, model, trim, model_year, vehicle_condition, mileage_km,
    price_minor, min_price_minor, currency, exterior_color, interior_color,
    engine, transmission, fuel, seats, features, status, steering,
    target_markets, stock_number, vin, specs, location, listed_at, sold_at,
    source
"""


def _money(amount: int | None, currency: str) -> dict[str, Any] | None:
    return None if amount is None else {"amount_minor": amount, "currency": currency}


def _present(row: Any) -> dict[str, Any]:
    data = dict(row)
    currency = data.pop("currency", "AED")
    data["price"] = _money(data.pop("price_minor", None), currency)
    data["min_price"] = _money(data.pop("min_price_minor", None), currency)
    return data


# --------------------------------------------------------------------------
# read
# --------------------------------------------------------------------------


@router.get("", response_model=list[VehicleOut])
async def list_vehicles(
    ctx: Ctx,
    status_filter: Annotated[VehicleStatus | None, Query(alias="status")] = None,
    make: str | None = None,
    model: str | None = None,
    max_price_minor: int | None = None,
    stale_days: int | None = Query(default=None, ge=0),
    q: str | None = Query(default=None, description="matches make, model or stock number"),
    limit: int = Query(default=50, le=200),
) -> list[dict[str, Any]]:
    clauses: list[str] = ["tenant_id = $1"]
    args: list[Any] = [ctx.tenant_id]

    def add(sql: str, value: Any) -> None:
        args.append(value)
        clauses.append(sql.format(n=len(args)))

    if status_filter:
        add("status = ${n}", status_filter)
    if make:
        add("make ilike ${n}", make)
    if model:
        add("model ilike ${n}", model)
    if max_price_minor is not None:
        add("price_minor <= ${n}", max_price_minor)
    if stale_days is not None:
        add("listed_at <= now() - make_interval(days => ${n})", stale_days)
    if q:
        add("(make ilike ${n} or model ilike ${n} or stock_number ilike ${n})", f"%{q}%")

    args.append(limit)
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            f"select {_COLUMNS} from vehicles where {' and '.join(clauses)} "  # noqa: S608
            f"order by listed_at desc limit ${len(args)}",
            *args,
        )
    return [_present(r) for r in rows]


@router.get("/stock-report", response_model=list[StockRow])
async def stock_report(
    ctx: Ctx,
    min_days: int = Query(default=0, ge=0),
    uncovered_only: bool = Query(
        default=False, description="only vehicles with no published content"
    ),
) -> list[dict[str, Any]]:
    """Aging and content coverage — the report that answers 'what is not selling
    and what have we never posted about'."""
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            """select id, make, model, stock_number, status, price_minor, currency,
                      days_in_stock, published_content_count, last_content_at
               from v_vehicle_stock
               where tenant_id = $1
                 and status = 'available'
                 and days_in_stock >= $2
                 and ($3 = false or published_content_count = 0)
               order by days_in_stock desc""",
            ctx.tenant_id,
            min_days,
            uncovered_only,
        )
    out = []
    for row in rows:
        data = dict(row)
        currency = data.pop("currency", "AED")
        data["price"] = _money(data.pop("price_minor", None), currency)
        out.append(data)
    return out


@router.get("/{vehicle_id}", response_model=VehicleOut)
async def get_vehicle(vehicle_id: UUID, ctx: Ctx) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(
            f"select {_COLUMNS} from vehicles where id = $1",  # noqa: S608
            vehicle_id,
        )
    if row is None:
        raise NotFound("no such vehicle")
    return _present(row)


# --------------------------------------------------------------------------
# write
# --------------------------------------------------------------------------


@router.post("", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    body: VehicleCreate,
    ctx: Annotated[TenantContext, Depends(require_role("marketer"))],
) -> dict[str, Any]:
    fields = body.model_dump()
    names = ["tenant_id", *fields]
    values = [ctx.tenant_id, *fields.values()]
    placeholders = ", ".join(f"${i + 1}" for i in range(len(values)))

    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        try:
            row = await conn.fetchrow(
                f"insert into vehicles ({', '.join(names)}) values ({placeholders}) "  # noqa: S608
                f"returning {_COLUMNS}",
                *values,
            )
        except asyncpg.UniqueViolationError as exc:
            raise Conflict("a vehicle with that stock number or VIN already exists") from exc
        await emit(conn, "vehicle.created", {"vehicle_id": str(row["id"])}, tenant_id=ctx.tenant_id)
    return _present(row)


@router.patch("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: UUID,
    body: VehicleUpdate,
    ctx: Annotated[TenantContext, Depends(require_role("marketer"))],
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        return await get_vehicle(vehicle_id, ctx)

    # Column names come from VehicleUpdate's own fields, never from user input.
    assignments = ", ".join(f"{name} = ${i + 2}" for i, name in enumerate(fields))
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(
            f"update vehicles set {assignments} where id = $1 returning {_COLUMNS}",  # noqa: S608
            vehicle_id,
            *fields.values(),
        )
    if row is None:
        raise NotFound("no such vehicle")
    return _present(row)


@router.post("/{vehicle_id}/status", response_model=VehicleOut)
async def change_status(
    vehicle_id: UUID,
    body: StatusChange,
    ctx: Annotated[TenantContext, Depends(require_role("marketer"))],
) -> dict[str, Any]:
    """Change availability.

    Selling a car emits `vehicle.sold`, whose handler cancels every scheduled
    content item and paused ad that references it. Marketing a car that is gone
    is the most visible way this product can embarrass a dealer, so the cascade
    is an event rather than something each caller has to remember.
    """
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        row = await conn.fetchrow(
            f"""update vehicles
                   set status = $2,
                       sold_at = case when $2 = 'sold' then now() else sold_at end
                 where id = $1
             returning {_COLUMNS}""",  # noqa: S608
            vehicle_id,
            body.status,
        )
        if row is None:
            raise NotFound("no such vehicle")

        await emit(
            conn,
            f"vehicle.{body.status}" if body.status == "sold" else "vehicle.status_changed",
            {
                "vehicle_id": str(vehicle_id),
                "status": body.status,
                "reason": body.reason,
            },
            tenant_id=ctx.tenant_id,
            priority=5 if body.status == "sold" else 0,
        )
    return _present(row)


@router.post("/{vehicle_id}/price", response_model=VehicleOut)
async def change_price(
    vehicle_id: UUID,
    body: PriceChange,
    ctx: Annotated[TenantContext, Depends(require_role("admin"))],
) -> dict[str, Any]:
    """Set the list price. Always writes history, always emits.

    Published content shows a price. Changing it without telling anything else
    leaves posts and ads quoting a number the dealer no longer honours, so the
    history row and the event are part of the same transaction as the update.
    """
    async with tenant_session(ctx.tenant_id) as conn, conn.transaction():
        current = await conn.fetchrow(
            "select price_minor, currency from vehicles where id = $1 for update", vehicle_id
        )
        if current is None:
            raise NotFound("no such vehicle")

        row = await conn.fetchrow(
            f"update vehicles set price_minor = $2 where id = $1 returning {_COLUMNS}",  # noqa: S608
            vehicle_id,
            body.amount_minor,
        )
        await conn.execute(
            """insert into vehicle_price_history
                   (tenant_id, vehicle_id, price_minor, currency, reason, actor_type, actor_id)
               values ($1,$2,$3,$4,$5,'user',$6)""",
            ctx.tenant_id,
            vehicle_id,
            body.amount_minor,
            current["currency"],
            body.reason,
            str(ctx.user.id),
        )
        if current["price_minor"] != body.amount_minor:
            await emit(
                conn,
                "vehicle.price_changed",
                {
                    "vehicle_id": str(vehicle_id),
                    "before_minor": current["price_minor"],
                    "after_minor": body.amount_minor,
                    "currency": current["currency"],
                },
                tenant_id=ctx.tenant_id,
                priority=5,
            )
    return _present(row)
