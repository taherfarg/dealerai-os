"""The vehicle lifecycle's events. See docs/lifecycle/README.md."""

from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from ...core.money import Money
from ...core.words import Words
from ...db.session import tenant_session
from ...lifecycle import pricing
from ..bus import Event, handler
from .notify import notify

log = structlog.get_logger()

#: Who hears that prices should move: whoever may change them.
PRICE_DECIDERS = ("owner", "admin")
#: Who hears that published content quotes an old price: whoever can take it down.
CONTENT_OWNERS = ("owner", "admin", "marketer")


async def _members(conn: asyncpg.Connection, tenant_id: UUID, roles: tuple[str, ...]) -> list[UUID]:
    rows = await conn.fetch(
        "select user_id from memberships where tenant_id = $1 and role = any($2::text[])",
        tenant_id,
        list(roles),
    )
    return [row["user_id"] for row in rows]


@handler("pricing.sweep_due")
async def on_pricing_sweep(event: Event) -> None:
    """Every morning, before the brief: every available car, priced against its
    cost, its age and its demand, and a proposal for each that should move.

    One notification for the morning, not one per car. Six proposals is one
    thing to look at, and six interruptions is how a bell gets muted.
    """
    tenant_id = event.tenant_id
    if tenant_id is None:
        raise ValueError("pricing.sweep_due requires a tenant")
    day = str(event.payload.get("date") or "")

    async with tenant_session(tenant_id) as conn, conn.transaction():
        counts = await pricing.sweep(conn, tenant_id)
        if counts["proposed"]:
            n = counts["proposed"]
            for user_id in await _members(conn, tenant_id, PRICE_DECIDERS):
                await notify(
                    conn,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind="price_proposed",
                    title=Words(
                        f"{n} price change{'s' if n != 1 else ''} proposed",
                        f"اقتراح تغيير سعر {n} سيارة",
                    ),
                    body=Words(
                        "Cars that have aged past your pricing ladder. Approve or reject each.",
                        "سيارات تجاوزت مدة البقاء في سلّم التسعير. وافق أو ارفض كل اقتراح.",
                    ),
                    entity={"type": "approval_queue", "id": day or "pricing"},
                    dedupe_key=f"price_proposed:{day}",
                )
    log.info("pricing_swept", tenant_id=str(tenant_id), **counts)


async def after_price_change(event: Event) -> None:
    """Content that still quotes the old price.

    Called from the copilot's vehicle.price_changed handler: the bus allows one
    handler per event, and both concerns hang off the same moment. Unpublished
    pieces are stopped; published ones are named to whoever can take them
    down, because nothing here can.
    """
    tenant_id = event.tenant_id
    if tenant_id is None:
        return
    vehicle_id = UUID(str(event.payload["vehicle_id"]))
    after = int(event.payload["after_minor"])
    currency = str(event.payload.get("currency") or "AED")

    async with tenant_session(tenant_id) as conn, conn.transaction():
        found = await pricing.stale_content(conn, vehicle_id, price_minor=after, currency=currency)
        if found["published"]:
            n = len(found["published"])
            price = str(Money(after, currency))
            for user_id in await _members(conn, tenant_id, CONTENT_OWNERS):
                await notify(
                    conn,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind="content_stale",
                    title=Words(
                        f"{n} published post{'s' if n != 1 else ''} quote an old price",
                        f"{n} من المنشورات المنشورة تذكر سعرًا قديمًا",
                    ),
                    body=Words(
                        f"The price is now {price}. Take them down or correct them.",
                        f"السعر الآن {price}. احذفها أو صحّحها.",
                    ),
                    entity={"type": "vehicle", "id": str(vehicle_id)},
                    dedupe_key=f"content_stale:{vehicle_id}:{after}",
                )
    if found["stopped"] or found["published"]:
        log.info(
            "stale_content",
            vehicle_id=str(vehicle_id),
            stopped=len(found["stopped"]),
            published=len(found["published"]),
        )
