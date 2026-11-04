"""The vehicle lifecycle's events. See docs/lifecycle/README.md."""

from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from ...core.money import Money
from ...core.words import Words, same
from ...db.session import tenant_session
from ...lifecycle import pricing, recon
from ..bus import Event, handler
from .notify import notify

log = structlog.get_logger()

#: Who hears that prices should move, or a repair needs more money: whoever
#: may decide it.
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


@handler("approval.requested")
async def on_approval_requested(event: Event) -> None:
    """A repair that would take a car over budget, told to whoever decides it,
    the moment it is asked — the work is waiting on them.

    Every approval emits this; only reconditioning rings a bell here. Price
    proposals are told once a morning by the sweep, and the reviewer's queue for
    the other kinds is M4's (docs/09-implementation-plan.md).
    """
    tenant_id = event.tenant_id
    if tenant_id is None or event.payload.get("kind") != recon.KIND:
        return
    approval_id = str(event.payload["approval_id"])
    summary = str(event.payload.get("summary") or "")
    async with tenant_session(tenant_id) as conn, conn.transaction():
        for user_id in await _members(conn, tenant_id, PRICE_DECIDERS):
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind="recon_approval",
                title=Words("A repair needs your approval", "إصلاح ينتظر موافقتك"),
                # The car, the work and the amounts: numbers and names read the
                # same in either language.
                body=same(summary),
                entity={"type": "approval_queue", "id": approval_id},
                dedupe_key=f"recon_approval:{approval_id}",
            )


@handler("recon.overran")
async def on_recon_overran(event: Event) -> None:
    """A repair came in above its estimate and took the car over budget. The
    money is spent — there is nothing to approve — so the owner is told."""
    tenant_id = event.tenant_id
    if tenant_id is None:
        return
    payload = event.payload
    currency = str(payload.get("currency") or "AED")
    actual = Money(int(payload["actual_minor"]), currency).display()
    estimate = Money(int(payload["estimate_minor"]), currency).display()
    over = Money(int(payload["over_minor"]), currency).display()
    what = str(payload.get("description") or "")
    async with tenant_session(tenant_id) as conn, conn.transaction():
        for user_id in await _members(conn, tenant_id, PRICE_DECIDERS):
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind="recon_overrun",
                title=Words(
                    f"A repair is {over} over budget", f"إصلاح تجاوز الميزانية بمقدار {over}"
                ),
                body=Words(
                    f"{what}: {actual}, estimated at {estimate}.",
                    f"{what}: {actual}، والتقدير كان {estimate}.",
                ),
                entity={"type": "vehicle", "id": str(payload["vehicle_id"])},
                dedupe_key=f"recon_overrun:{payload['item_id']}",
            )
