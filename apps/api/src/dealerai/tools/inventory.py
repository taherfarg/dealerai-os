"""Inventory tools: the only way an agent learns anything about a car.

Every one of these runs through `tenant_session`, so RLS decides what a query
can see. That is what makes the cross-tenant case boring rather than clever —
asking for another dealership's vehicle returns nothing, not because a check
rejected it but because the row is not there.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from ..db.session import tenant_session
from ..deps import TenantContext
from .registry import tool

GROUP = "inventory"

#: What a customer-facing agent may see. `min_price_minor` is deliberately
#: absent — it is the discount floor, and an agent that can read it will reason
#: its way down to it. See docs/03-database-schema.md § 3.
_SUMMARY = """
    id, make, model, trim, model_year, vehicle_condition, mileage_km,
    price_minor, currency, exterior_color, interior_color, engine,
    transmission, fuel, seats, features, status, steering, target_markets
"""


def _present(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["id"] = str(data["id"])
    return data


@tool(name="search_inventory", group=GROUP)
async def search_inventory(
    ctx: TenantContext,
    *,
    make: str | None = None,
    model: str | None = None,
    max_price_minor: int | None = None,
    min_days_in_stock: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search this dealership's live inventory.

    Returns only vehicles currently in stock and available for sale. Prices are
    in minor units — 6600000 means AED 66,000.00. Never quote a price that did
    not come back from this tool.
    """
    clauses = ["tenant_id = $1", "status = 'available'"]
    args: list[Any] = [ctx.tenant_id]

    def add(sql: str, value: Any) -> None:
        args.append(value)
        clauses.append(sql.format(n=len(args)))

    if make:
        add("make ilike ${n}", make)
    if model:
        add("model ilike ${n}", model)
    if max_price_minor is not None:
        add("price_minor <= ${n}", max_price_minor)
    if min_days_in_stock is not None:
        add("listed_at <= now() - make_interval(days => ${n})", min_days_in_stock)

    args.append(min(limit, 50))
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            f"select {_SUMMARY} from vehicles where {' and '.join(clauses)} "  # noqa: S608
            f"order by listed_at desc limit ${len(args)}",
            *args,
        )
    return [_present(r) for r in rows]


@tool(name="get_vehicle", group=GROUP)
async def get_vehicle(ctx: TenantContext, *, vehicle_id: str) -> dict[str, Any] | None:
    """Look up one vehicle by its id.

    Returns null if this dealership has no such vehicle. A null means the car
    does not exist here — say so. Do not describe a vehicle this did not return.
    """
    try:
        parsed = UUID(vehicle_id)
    except ValueError:
        return None
    async with tenant_session(ctx.tenant_id) as conn:
        row = await conn.fetchrow(
            f"select {_SUMMARY} from vehicles where id = $1",  # noqa: S608
            parsed,
        )
    return _present(row) if row else None


@tool(name="get_vehicle_media", group=GROUP)
async def get_vehicle_media(
    ctx: TenantContext, *, vehicle_id: str, usable_only: bool = True
) -> list[dict[str, Any]]:
    """The photographs on a vehicle, best first.

    `is_hero` marks the single shot chosen to lead the listing. `angle` is one
    of the twelve camera positions. Rejected photos are excluded unless you ask
    for them, and a rejected photo must never be published.
    """
    try:
        parsed = UUID(vehicle_id)
    except ValueError:
        return []
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            """select id, storage_path, angle, quality_score, is_hero, sort_order,
                      coalesce(qa->>'rejected', 'false')::boolean as rejected
                 from vehicle_media
                where vehicle_id = $1 and kind = 'photo'
                order by sort_order""",
            parsed,
        )
    media = [dict(r) | {"id": str(r["id"])} for r in rows]
    return [m for m in media if not m["rejected"]] if usable_only else media


@tool(name="days_in_stock", group=GROUP)
async def days_in_stock(ctx: TenantContext, *, vehicle_id: str) -> int | None:
    """How long a vehicle has been listed, in days.

    Aging stock is the reason most campaigns exist. Null means no such vehicle.
    """
    try:
        parsed = UUID(vehicle_id)
    except ValueError:
        return None
    async with tenant_session(ctx.tenant_id) as conn:
        value = await conn.fetchval(
            "select extract(day from now() - listed_at)::int from vehicles where id = $1", parsed
        )
    return int(value) if value is not None else None


@tool(name="price_history", group=GROUP)
async def price_history(
    ctx: TenantContext, *, vehicle_id: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Past list prices for a vehicle, newest first.

    Use it to know whether a price has already moved. It is history, not an
    offer: only the current price may be quoted to a customer.
    """
    try:
        parsed = UUID(vehicle_id)
    except ValueError:
        return []
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            """select price_minor, currency, reason, created_at
                 from vehicle_price_history
                where vehicle_id = $1 order by created_at desc limit $2""",
            parsed,
            min(limit, 50),
        )
    return [dict(r) for r in rows]


@tool(name="stock_report", group=GROUP)
async def stock_report(
    ctx: TenantContext,
    *,
    min_days: int = 0,
    coverage: Literal["all", "uncovered"] = "all",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Available stock with its age and how much content it already has.

    `uncovered` narrows it to vehicles nothing has ever been posted about, which
    is usually where a content plan should start.
    """
    async with tenant_session(ctx.tenant_id) as conn:
        rows = await conn.fetch(
            """select id, make, model, stock_number, price_minor, currency,
                      days_in_stock, published_content_count, last_content_at
                 from v_vehicle_stock
                where tenant_id = $1 and status = 'available' and days_in_stock >= $2
                  and ($3 = 'all' or published_content_count = 0)
                order by days_in_stock desc limit $4""",
            ctx.tenant_id,
            min_days,
            coverage,
            min(limit, 200),
        )
    return [_present(r) for r in rows]
